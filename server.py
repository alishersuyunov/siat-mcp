"""
MCP Server for Uzbekistan official statistics.

Sources
-------
siat.stat.uz   — National Statistics Committee SIAT portal (JSON API)
nsdp.stat.uz   — National Summary Data Page, IMF DSBB-compliant (SDMX 2.1 XML)
hudud.stat.uz  — Regional statistics portal (GIS indicators + regional passport)

SIAT Catalog API: GET https://siat.stat.uz/api/sdmx/json/
SIAT Data API:    GET https://siat.stat.uz/media/uploads/sdmx/sdmx_data_{id}.json
NSDP data:        static SDMX 2.1 XML files hosted on stat.uz, cbu.uz, api.mf.uz, uzse.uz
hudud GIS API:    GET https://hudud.stat.uz/api/v1/gis/...
hudud Passport:   GET https://hudud.stat.uz/api/v1/passport/...
"""

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

try:
    import orjson
    _ORJSON = True
except ImportError:
    _ORJSON = False

try:
    from asyncache import cached
    from cachetools import LRUCache, TTLCache
    _CACHE = True
except ImportError:
    _CACHE = False

BASE_URL = "https://siat.stat.uz"
CATALOG_URL = f"{BASE_URL}/api/sdmx/json/"
DATA_URL = f"{BASE_URL}/media/uploads/sdmx/sdmx_data_{{id}}.json"

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "uz",
    "origin": BASE_URL,
    "referer": f"{BASE_URL}/",
}

HUDUD_BASE_URL = "https://hudud.stat.uz"
HUDUD_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "uz",
    "origin": HUDUD_BASE_URL,
    "referer": f"{HUDUD_BASE_URL}/",
}

# ---------------------------------------------------------------------------
# NSDP (nsdp.stat.uz) — static SDMX 2.1 XML files
# ---------------------------------------------------------------------------

NSDP_HEADERS = {
    "accept": "application/xml, text/xml, */*",
    "accept-language": "en",
    "user-agent": "siat-mcp/1.0",
}

NSDP_CATALOG: dict[str, dict] = {
    "NAG":  {"name": "National Accounts (GDP)",           "xml_url": "https://stat.uz/img/uploads/download_xml/nag_uzbekistan_mcd.xml",                   "freq": "A/Q"},
    "CPI":  {"name": "Consumer Price Index",              "xml_url": "https://stat.uz/img/uploads/download_xml/cpi_uzbekistan_mcd_online.xml",             "freq": "M"},
    "GGO":  {"name": "General Government Operations",     "xml_url": "https://api.mf.uz/media/budget_activity_files/CGO_Uzbekistan_Online_m50MA36.xml",    "freq": "M"},
    "CGO":  {"name": "Central Government Operations",     "xml_url": "https://api.mf.uz/media/budget_activity_files/GGO_Uzbekistan_Online_7zivz5i.xml",    "freq": "M"},
    "CGD":  {"name": "Central Government Gross Debt",     "xml_url": "https://api.mf.uz/media/GDDS/CGD_Uzbekistan_MCD_.xml",                               "freq": "Q"},
    "DCS":  {"name": "Depository Corporations Survey",    "xml_url": "https://cbu.uz/sdmx/DCS_Uzbekistan_Online.xml",                                       "freq": "M"},
    "CBS":  {"name": "Central Bank Survey",               "xml_url": "https://cbu.uz/sdmx/CBS_Uzbekistan_Online.xml",                                       "freq": "M"},
    "INR":  {"name": "Interest Rates",                    "xml_url": "https://cbu.uz/sdmx/INR_Uzbekistan_STA.xml",                                          "freq": "M"},
    "SPI":  {"name": "Stock Market Index",                "xml_url": "https://uzse.uz/api/v1/static_files/data.xml",                                        "freq": "M"},
    "BOP":  {"name": "Balance of Payments",               "xml_url": "https://cbu.uz/sdmx/BOP_Analytical_Uzbekistan.xml",                                   "freq": "Q/A"},
    "EXD":  {"name": "External Debt",                     "xml_url": "https://cbu.uz/sdmx/EXD_Uzbekistan_QEDS.xml",                                        "freq": "Q"},
    "ILV":  {"name": "Official Reserve Assets",           "xml_url": "https://cbu.uz/sdmx/IR_Uzbekistan_MCD_STA.xml",                                       "freq": "M"},
    "MET":  {"name": "Merchandise Trade",                 "xml_url": "https://stat.uz/img/uploads/download_xml/met_uzbekistan_online_mcd.xml",             "freq": "M"},
    "IIP":  {"name": "International Investment Position", "xml_url": "https://cbu.uz/sdmx/IIP_analytical_Uzbekistan.xml",                                   "freq": "Q/A"},
    "EXR":  {"name": "Exchange Rates",                    "xml_url": "https://cbu.uz/sdmx/EXR_Uzbekistan_STA.xml",                                         "freq": "M"},
    "IND":  {"name": "Production Index",                  "xml_url": "https://stat.uz/img/uploads/download_xml/ind_uzbekistan_online_mcd.xml",             "freq": "M"},
    "LMI":  {"name": "Labor Market Indicators",           "xml_url": "https://stat.uz/img/uploads/download_xml/lmi_uzbekistan_online.xml",                 "freq": "A/Q"},
    "PPI":  {"name": "Producer Price Index",              "xml_url": "https://stat.uz/img/uploads/download_xml/ppi_uzbekistan_online_mcd.xml",             "freq": "M"},
    "FSI":  {"name": "Financial Soundness Indicators",    "xml_url": "https://cbu.uz/sdmx/FSD_Uzbekistan_STA_IMF.xml",                                      "freq": "Q"},
    "POP":  {"name": "Population",                        "xml_url": "https://stat.uz/img/uploads/download_xml/pop_uzbekistan_online.xml",                 "freq": "A"},
    "SDG":  {"name": "Socio-Demographic Indicators",      "xml_url": "https://stat.uz/img/uploads/download_xml/sdg_uzbekistan_online.xml",                 "freq": "A"},
    "DOTS": {"name": "Direction of Trade Statistics",     "xml_url": "https://stat.uz/img/uploads/download_xml/dots_uzbekistan_sta.xml",                   "freq": "A/Q"},
}

mcp = FastMCP("siat-stat-uz", dependencies=["httpx"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_name(item: dict, lang: str = "en") -> str:
    """Return the name of an item in the requested language (fallback chain)."""
    for key in (f"name_{lang}", "name_en", "name_uz", "name"):
        value = item.get(key)
        if value:
            return value
    return str(item.get("id", "unknown"))


def _flatten_catalog(nodes: list[dict], lang: str = "en") -> list[dict]:
    """Recursively flatten the catalog tree into a list of leaf datasets."""
    results: list[dict] = []
    for node in nodes:
        children = node.get("children") or []
        if children:
            results.extend(_flatten_catalog(children, lang))
        else:
            results.append({
                "id": node.get("id"),
                "name": _get_name(node, lang),
                "name_uz": node.get("name_uz"),
                "name_ru": node.get("name_ru"),
                "name_en": node.get("name_en"),
                "code": node.get("code"),
                "period": node.get("period"),
                "updated_at": node.get("updated_at"),
                "status": node.get("status"),
            })
    return results


def _search_tree(
    nodes: list[dict],
    query: str,
    lang: str = "en",
    path: str = "",
) -> list[dict]:
    """DFS search through catalog tree for items whose name matches query."""
    query_lower = query.lower()
    results: list[dict] = []
    for node in nodes:
        name = _get_name(node, lang)
        current_path = f"{path} > {name}" if path else name
        children = node.get("children") or []
        if query_lower in name.lower():
            results.append({
                "id": node.get("id"),
                "name": name,
                "code": node.get("code"),
                "path": current_path,
                "has_children": bool(children),
                "period": node.get("period"),
                "updated_at": node.get("updated_at"),
                "status": node.get("status"),
            })
        if children:
            results.extend(_search_tree(children, query, lang, current_path))
    return results


def _top_level_summary(nodes: list[dict], lang: str = "en") -> list[dict]:
    """Return summary of top-level categories."""
    return [
        {
            "id": n.get("id"),
            "name": _get_name(n, lang),
            "code": n.get("code"),
            "children_count": len(n.get("children") or []),
        }
        for n in nodes
    ]


def _find_by_id(nodes: list[dict], target_id: int) -> dict | None:
    """Find a node by id anywhere in the tree."""
    for node in nodes:
        if node.get("id") == target_id:
            return node
        children = node.get("children") or []
        found = _find_by_id(children, target_id)
        if found:
            return found
    return None


def _dump_json(obj: Any) -> str:
    if _ORJSON:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2).decode("utf-8")
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _parse_sdmx_xml(content: bytes) -> dict:
    """Parse an SDMX 2.1 StructureSpecificData XML into a structured dict.

    Returns {"prepared": str, "reporting_period": str, "series": [...]}.
    Each series: {indicator, freq, unit_mult, dimensions, observations}.
    """
    def _local(tag: str) -> str:
        """Strip Clark-notation namespace, e.g. '{urn:...}Series' → 'Series'."""
        return tag.split("}", 1)[-1] if "}" in tag else tag

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"SDMX XML parse error: {exc}") from exc

    prepared = ""
    reporting_period = ""
    for child in root:
        if _local(child.tag) == "Header":
            for hchild in child:
                lname = _local(hchild.tag)
                if lname == "Prepared":
                    prepared = (hchild.text or "").strip()
                elif lname == "ReportingBegin":
                    for sub in hchild:
                        if _local(sub.tag) == "StandardTimePeriod":
                            reporting_period = (sub.text or "").strip()
            break

    series_list: list[dict] = []
    for child in root:
        if _local(child.tag) == "DataSet":
            for el in child:
                if _local(el.tag) != "Series":
                    continue
                dims = dict(el.attrib)
                unit_mult_str = dims.get("UNIT_MULT")
                try:
                    unit_mult: int | None = int(unit_mult_str) if unit_mult_str is not None else None
                except ValueError:
                    unit_mult = None

                observations: list[dict] = []
                for obs in el:
                    if _local(obs.tag) != "Obs":
                        continue
                    raw_val = obs.attrib.get("OBS_VALUE")
                    try:
                        value: float | None = float(raw_val) if raw_val is not None else None
                    except (ValueError, TypeError):
                        value = None
                    observations.append({
                        "time_period": obs.attrib.get("TIME_PERIOD", ""),
                        "value": value,
                    })

                series_list.append({
                    "indicator": dims.get("INDICATOR", ""),
                    "freq": dims.get("FREQ", ""),
                    "unit_mult": unit_mult,
                    "dimensions": dims,
                    "observations": observations,
                })
            break

    return {
        "prepared": prepared,
        "reporting_period": reporting_period,
        "series": series_list,
    }


# ---------------------------------------------------------------------------
# Client & Caching
# ---------------------------------------------------------------------------
_http_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(headers=HEADERS, timeout=60.0)
    return _http_client


_nsdp_http_client: httpx.AsyncClient | None = None

def _get_nsdp_client() -> httpx.AsyncClient:
    global _nsdp_http_client
    if _nsdp_http_client is None:
        _nsdp_http_client = httpx.AsyncClient(headers=NSDP_HEADERS, timeout=60.0)
    return _nsdp_http_client


_hudud_http_client: httpx.AsyncClient | None = None

def _get_hudud_client() -> httpx.AsyncClient:
    global _hudud_http_client
    if _hudud_http_client is None:
        _hudud_http_client = httpx.AsyncClient(headers=HUDUD_HEADERS, timeout=60.0)
    return _hudud_http_client


async def _hudud_get(path: str, params: dict | None = None) -> Any:
    client = _get_hudud_client()
    url = f"{HUDUD_BASE_URL}{path}"
    r = await client.get(url, params=params)
    r.raise_for_status()
    return orjson.loads(r.content) if _ORJSON else r.json()


async def _fetch_catalog() -> list[dict]:
    client = _get_client()
    r = await client.get(CATALOG_URL)
    r.raise_for_status()
    return orjson.loads(r.content) if _ORJSON else r.json()


async def _fetch_dataset(dataset_id: int) -> dict:
    """Return the inner {metadata, data} object for a dataset."""
    url = DATA_URL.format(id=dataset_id)
    client = _get_client()
    r = await client.get(url)
    r.raise_for_status()
    raw = orjson.loads(r.content) if _ORJSON else r.json()

    # Response is a 1-element list wrapping {metadata, data}
    if isinstance(raw, list) and raw:
        obj = raw[0]
    else:
        obj = raw
    if not isinstance(obj, dict) or "metadata" not in obj or "data" not in obj:
        raise ValueError(f"Unexpected dataset format: {str(obj)[:200]}")
    return obj


async def _fetch_nsdp_xml(url: str) -> bytes:
    """Fetch a raw SDMX XML file from nsdp.stat.uz (or its hosting domains)."""
    client = _get_nsdp_client()
    r = await client.get(url)
    r.raise_for_status()
    return r.content


async def _hudud_get_cached_regions() -> list:
    return await _hudud_get("/api/v1/gis/regions/", {"show_children": "true"})


async def _hudud_get_cached_spheres() -> list:
    return await _hudud_get("/api/v1/gis/spheres/")


if _CACHE:
    _fetch_catalog = cached(cache=TTLCache(maxsize=1, ttl=3600))(_fetch_catalog)
    _fetch_dataset = cached(cache=LRUCache(maxsize=5))(_fetch_dataset)
    _fetch_nsdp_xml = cached(cache=TTLCache(maxsize=10, ttl=6 * 3600))(_fetch_nsdp_xml)
    _hudud_get_cached_regions = cached(cache=TTLCache(maxsize=1, ttl=3600))(_hudud_get_cached_regions)
    _hudud_get_cached_spheres = cached(cache=TTLCache(maxsize=1, ttl=3600))(_hudud_get_cached_spheres)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_categories(lang: str = "en") -> str:
    """
    List the top-level statistical categories from the siat.stat.uz catalog.

    Args:
        lang: Language for names — "en" (English), "uz" (Uzbek Latin),
              "ru" (Russian), "uzc" (Uzbek Cyrillic). Defaults to "en".

    Returns:
        JSON array of top-level categories with their id, name, code, and
        number of child items.
    """
    catalog = await _fetch_catalog()
    summary = _top_level_summary(catalog, lang)
    return _dump_json(summary)


@mcp.tool()
async def search_catalog(query: str, lang: str = "en") -> str:
    """
    Search the siat.stat.uz data catalog for datasets or categories matching
    a keyword or phrase.

    Args:
        query: Keyword or phrase to search for (case-insensitive).
        lang:  Language to search in — "en", "uz", "ru", "uzc". Defaults "en".

    Returns:
        JSON array of matching items with id, name, code, path in the catalog
        hierarchy, whether they have children, period, updated_at, and status.
        Items without children are leaf datasets (directly retrievable).
    """
    catalog = await _fetch_catalog()
    results = _search_tree(catalog, query, lang)
    if not results:
        return _dump_json({"message": f"No results found for '{query}'."})
    return _dump_json(results)


@mcp.tool()
async def get_category(category_id: int, lang: str = "en") -> str:
    """
    Get the contents of a specific category by its id, showing its immediate
    children (sub-categories or datasets).

    Args:
        category_id: The numeric id of the category (from list_categories or
                     search_catalog).
        lang: Language for names — "en", "uz", "ru", "uzc". Defaults "en".

    Returns:
        JSON object with the category name and a "children" array. Each child
        includes id, name, code, has_children flag, period, updated_at, status.
        Children without sub-children are leaf datasets you can retrieve with
        get_dataset.
    """
    catalog = await _fetch_catalog()
    node = _find_by_id(catalog, category_id)
    if node is None:
        return _dump_json({"error": f"Category {category_id} not found."})

    children = node.get("children") or []
    return _dump_json(
        {
            "id": node.get("id"),
            "name": _get_name(node, lang),
            "code": node.get("code"),
            "children": [
                {
                    "id": c.get("id"),
                    "name": _get_name(c, lang),
                    "code": c.get("code"),
                    "has_children": bool(c.get("children")),
                    "period": c.get("period"),
                    "updated_at": c.get("updated_at"),
                    "status": c.get("status"),
                }
                for c in children
            ],
        }
    )


@mcp.tool()
async def list_datasets(lang: str = "en") -> str:
    """
    Return a flat list of all leaf datasets in the siat.stat.uz catalog
    (i.e. every entry that has actual data, not just sub-categories).

    Args:
        lang: Language for names — "en", "uz", "ru", "uzc". Defaults "en".

    Returns:
        JSON array of datasets. Each item has id, name (in requested language),
        name_uz, name_ru, name_en, code, period, updated_at, status.
        Use the id with get_dataset to retrieve the actual data.
    """
    catalog = await _fetch_catalog()
    datasets = _flatten_catalog(catalog, lang)
    return _dump_json(datasets)


@mcp.tool()
async def get_dataset(dataset_id: int, lang: str = "en") -> str:
    """
    Retrieve statistical data for a specific dataset from siat.stat.uz.

    Args:
        dataset_id: Numeric id of the dataset (obtain from search_catalog,
                    get_category, or list_datasets).
        lang:       Language for labels — "en", "uz", "ru", "uzc". Default "en".

    Returns:
        JSON object with:
          - "metadata": list of field descriptors (indicator name, unit,
            periodicity, source, etc.) in the requested language.
          - "data": list of observation records. Each record contains region /
            classifier labels and year-keyed numeric values (e.g. "2020": 1234.5).
          - "summary": quick human-readable description of what the dataset
            contains (indicator name, unit, years covered, number of regions).
    """
    try:
        obj = await _fetch_dataset(dataset_id)
    except Exception as e:
        return _dump_json({"error": str(e)})

    metadata_raw: list[dict] = obj["metadata"]
    data_raw: list[dict] = obj["data"]

    name_key = f"name_{lang}"
    value_key = f"value_{lang}"

    # Normalise metadata
    metadata: list[dict[str, Any]] = []
    for field in metadata_raw:
        entry: dict[str, Any] = {
            "name": field.get(name_key) or field.get("name_en") or field.get("name_uz", ""),
            "value": field.get(value_key) or field.get("value_en") or field.get("value_uz"),
        }
        metadata.append(entry)

    # Normalise data rows — one preferred-language label + year columns
    klassif_key = f"Klassifikator_{lang}" if lang != "uz" else "Klassifikator"
    data: list[dict[str, Any]] = []
    for row in data_raw:
        record: dict[str, Any] = {"code": row.get("Code", "")}
        # Classifier label in the requested language (fallback chain)
        record["region"] = (
            row.get(klassif_key)
            or row.get("Klassifikator_en")
            or row.get("Klassifikator")
            or ""
        )
        # Year-keyed numeric values
        for k, v in row.items():
            if re.match(r"^\d{4}$", k):
                record[k] = v
        data.append(record)

    # Build summary
    year_keys = sorted(k for k in (data[0] if data else {}) if re.match(r"^\d{4}$", k))
    indicator = next(
        (m["value"] for m in metadata if (m.get("name") or "").lower() == "indicator name"),
        None,
    ) or next(
        (m["value"] for m in metadata if "indicator name" in (m.get("name") or "").lower()),
        None,
    )
    unit = next(
        (m["value"] for m in metadata if "unit" in (m.get("name") or "").lower()),
        None,
    )
    summary = {
        "indicator": indicator,
        "unit": unit,
        "years": f"{year_keys[0]}–{year_keys[-1]}" if year_keys else "unknown",
        "num_regions": len(data),
    }

    return _dump_json({"summary": summary, "metadata": metadata, "data": data})


@mcp.tool()
async def get_dataset_metadata(dataset_id: int, lang: str = "en") -> str:
    """
    Retrieve only the metadata (field descriptions) of a dataset without
    downloading the full data table. Useful for previewing what a dataset
    contains before fetching it.

    Args:
        dataset_id: Numeric id of the dataset.
        lang:       Language — "en", "uz", "ru", "uzc". Default "en".

    Returns:
        JSON array of metadata fields: indicator name, unit of measurement,
        periodicity, data source, and other descriptors.
    """
    try:
        obj = await _fetch_dataset(dataset_id)
    except Exception as e:
        return _dump_json({"error": str(e)})

    metadata_raw: list[dict] = obj["metadata"]
    name_key = f"name_{lang}"
    value_key = f"value_{lang}"

    metadata = [
        {
            "name": f.get(name_key) or f.get("name_en") or f.get("name_uz", ""),
            "value": f.get(value_key) or f.get("value_en") or f.get("value_uz"),
        }
        for f in metadata_raw
    ]

    return _dump_json(metadata)


@mcp.tool()
async def nsdp_list_datasets() -> str:
    """
    List all 22 datasets available on nsdp.stat.uz — Uzbekistan's National
    Summary Data Page (IMF DSBB-compliant macroeconomic statistics). No
    network request is made; the catalog is static.

    Returns:
        JSON array of dataset entries. Each entry contains:
          - "code":    Short IMF/SDMX identifier (e.g. "NAG", "CPI", "BOP").
          - "name":    Human-readable dataset name in English.
          - "freq":    Publication frequency — "A" (annual), "M" (monthly),
                       "Q" (quarterly), or combinations like "A/Q".
          - "xml_url": Direct URL to the SDMX 2.1 XML file.
          - "source":  Hosting domain (stat.uz, cbu.uz, api.mf.uz, uzse.uz).
        Pass "code" to nsdp_get_dataset to retrieve the actual time-series data.
    """
    result = [
        {
            "code": code,
            "name": meta["name"],
            "freq": meta["freq"],
            "xml_url": meta["xml_url"],
            "source": meta["xml_url"].split("/")[2],
        }
        for code, meta in NSDP_CATALOG.items()
    ]
    return _dump_json(result)


@mcp.tool()
async def nsdp_get_dataset(indicator_code: str) -> str:
    """
    Fetch and parse an NSDP (nsdp.stat.uz) dataset by its IMF/SDMX indicator
    code. Data is delivered as SDMX 2.1 XML from stat.uz, cbu.uz, api.mf.uz,
    or uzse.uz, depending on the dataset.

    Args:
        indicator_code: IMF/SDMX dataset code, case-insensitive
                        (e.g. "NAG", "cpi", "BOP", "EXR").
                        Call nsdp_list_datasets to see all 22 available codes.

    Returns:
        JSON object with two top-level keys:
          - "dataset": descriptive metadata — name, code, prepared timestamp,
                       reporting_period, freq, xml_url, source domain.
          - "series":  list of time series. Each series contains:
              - "indicator":    SDMX INDICATOR dimension code
                                (e.g. "NGDP_PA_XDC", "PCPI_PC_PP_PT").
              - "freq":         Frequency code ("A", "Q", or "M").
              - "unit_mult":    Integer scale exponent (0 = units, 6 = millions,
                                9 = billions), or null if not present.
              - "dimensions":   All SDMX dimension attributes as key/value pairs.
              - "observations": list of {time_period, value} dicts.
                                time_period uses ISO 8601 (YYYY, YYYY-Qn,
                                YYYY-MM). value is a float, or null if the
                                source marks the observation as missing.
    """
    code = indicator_code.strip().upper()
    if code not in NSDP_CATALOG:
        available = ", ".join(sorted(NSDP_CATALOG))
        return _dump_json({"error": f"Unknown indicator code '{code}'. Available: {available}"})

    meta = NSDP_CATALOG[code]
    url = meta["xml_url"]
    try:
        content = await _fetch_nsdp_xml(url)
    except httpx.HTTPStatusError as exc:
        return _dump_json({"error": f"HTTP {exc.response.status_code} fetching {url}"})
    except httpx.RequestError as exc:
        return _dump_json({"error": f"Network error fetching {url}: {exc}"})

    try:
        parsed = _parse_sdmx_xml(content)
    except ValueError as exc:
        return _dump_json({"error": str(exc)})

    return _dump_json({
        "dataset": {
            "name": meta["name"],
            "code": code,
            "prepared": parsed["prepared"],
            "reporting_period": parsed["reporting_period"],
            "freq": meta["freq"],
            "xml_url": url,
            "source": url.split("/")[2],
        },
        "series": parsed["series"],
    })


# ---------------------------------------------------------------------------
# hudud.stat.uz — Regional Statistics Portal
# ---------------------------------------------------------------------------

@mcp.tool()
async def hudud_list_regions(parent_soato: str = "") -> str:
    """
    List administrative regions of Uzbekistan from hudud.stat.uz.

    When called without arguments returns all top-level regions (oblasts +
    Karakalpakstan Republic) with their immediate children (districts).
    Pass a parent_soato to get only the sub-regions of that region.

    Args:
        parent_soato: SOATO code of the parent region, e.g. "1735" for
                      Karakalpakstan or "1703" for Andijan oblast.
                      Leave empty to get the full hierarchy.

    Returns:
        JSON array of region objects. Each has:
          - "id":             internal numeric id
          - "soato":          SOATO administrative code (string)
          - "name":           name in Uzbek Latin
          - "name_ru":        name in Russian
          - "children_count": number of child districts
          - "area_km2":       area in square kilometers (may be null)
          - "siat_population": latest population estimate (thousand people)
          - "parent":         parent region object, or null for top-level
        For top-level call: also includes "childrens" list of child districts.
    """
    try:
        if parent_soato:
            data = await _hudud_get(
                "/api/v1/gis/regions/",
                {"parent__isnull": "false", "parent_soato": parent_soato},
            )
        else:
            data = await _hudud_get_cached_regions()
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_list_spheres() -> str:
    """
    List thematic spheres (indicator categories) available in the hudud.stat.uz
    GIS portal. Each sphere groups a set of regional statistical indicators.

    Returns:
        JSON array of sphere objects. Each has:
          - "id":       sphere id (use with hudud_get_sphere_indicators)
          - "title":    name in Uzbek Latin
          - "title_en": name in English
          - "title_ru": name in Russian
    """
    try:
        data = await _hudud_get_cached_spheres()
        return _dump_json([
            {
                "id": s.get("id"),
                "title": s.get("title"),
                "title_en": s.get("title_en"),
                "title_ru": s.get("title_ru"),
            }
            for s in data
        ])
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_sphere_indicators(sphere_id: int) -> str:
    """
    List all statistical indicators belonging to a specific thematic sphere
    in hudud.stat.uz.

    Args:
        sphere_id: Numeric id of the sphere (from hudud_list_spheres).

    Returns:
        JSON array of indicator objects. Each has:
          - "id":          indicator id (use with hudud_get_indicator_data)
          - "title_en":    indicator name in English
          - "title_uz":    indicator name in Uzbek Latin
          - "title_ru":    indicator name in Russian
          - "code":        internal indicator code
          - "sdmx_id":     linked SDMX dataset id (usable with get_dataset)
          - "period_en":   periodicity ("annual", "quarterly", "monthly")
          - "unit_en":     unit of measurement in English
    """
    try:
        data = await _hudud_get("/api/v1/gis/spheres/sdmx/", {"menu": sphere_id})
        return _dump_json([
            {
                "id": ind.get("id"),
                "title_en": ind.get("title_en"),
                "title_uz": ind.get("title_uz") or ind.get("title"),
                "title_ru": ind.get("title_ru"),
                "code": ind.get("code"),
                "sdmx_id": ind.get("sdmx_id"),
                "period_en": ind.get("period_en"),
                "unit_en": ind.get("unit_en"),
            }
            for ind in data
        ])
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_indicator_periods(indicator_id: int) -> str:
    """
    Get the list of available time periods for a specific GIS indicator on
    hudud.stat.uz.

    Args:
        indicator_id: Numeric indicator id (from hudud_get_sphere_indicators).

    Returns:
        JSON object with:
          - "id":         indicator id
          - "title":      indicator name
          - "period_en":  periodicity label
          - "periods":    list of {year, period} dicts.
                          For annual data, period is null; for monthly it is
                          "M01"–"M12"; for quarterly "Q1"–"Q4".
    """
    try:
        data = await _hudud_get(f"/api/v1/gis/sdmx/{indicator_id}/periods/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_indicator_data(
    indicator_id: int,
    soato: str = "",
    period: str = "",
) -> str:
    """
    Retrieve regional values for a GIS indicator from hudud.stat.uz.

    Args:
        indicator_id: Numeric indicator id (from hudud_get_sphere_indicators).
        soato:        SOATO code to filter by a specific region, e.g. "1735".
                      Leave empty to get data for all regions.
        period:       Period string, e.g. "2024", "2024-Q3", "2024-M06".
                      Leave empty to use the latest available period.

    Returns:
        JSON object with indicator metadata and a "data" section containing:
          - "min_value" / "max_value": range across regions
          - "period":   the period returned ("last" = latest available)
          - "soato":    the parent SOATO scope
          - "values":   list of regional observations, each with soato, value,
                        last_period, previous_value, growth_percentage.
    """
    try:
        data = await _hudud_get(
            f"/api/v1/gis/sdmx/{indicator_id}/",
            {"soato": soato, "period": period},
        )
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_indicator_metadata(indicator_id: int) -> str:
    """
    Get detailed metadata for a GIS indicator from hudud.stat.uz, including
    publication dates, source department, and all multilingual descriptors.

    Args:
        indicator_id: Numeric indicator id (from hudud_get_sphere_indicators).

    Returns:
        JSON object with indicator id, linked sdmx_id, and a "metadata" list
        of {name_en, name_ru, name_uz, value_en, value_ru, value_uz} entries
        describing the indicator's methodology, units, and publication history.
    """
    try:
        data = await _hudud_get(f"/api/v1/gis/sdmx-info/{indicator_id}/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_region_passport(soato: str = "") -> str:
    """
    Get the macro-economic and demographic summary card ("passport") for an
    administrative region from hudud.stat.uz.

    Args:
        soato: SOATO code of the region, e.g. "1735" for Karakalpakstan,
               "1703" for Andijan oblast. Leave empty for the national level.

    Returns:
        JSON object with a "MacroAndDemography" section containing four key
        indicator cards (population, economically active population, industrial
        output, foreign trade turnover). Each card has title, unit, periodicity,
        period, current value, and year-on-year growth percentage.
    """
    try:
        params = {"code": soato} if soato else {}
        data = await _hudud_get("/api/v1/passport/MacroEconomicAndDemographicIndicators/", params)
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_population_by_years(soato: str) -> str:
    """
    Get historical population data (2010–present) for each sub-region of
    the specified region from hudud.stat.uz.

    Args:
        soato: SOATO code of a region, e.g. "1700" (national), "1735"
               (Karakalpakstan), "1703" (Andijan). District codes also work.

    Returns:
        JSON object with "soato", "region" name, and "data" — a dict keyed
        by sub-region SOATO codes. Each sub-region entry contains its
        classifier labels (Uzbek, Russian, English, Cyrillic) and year-keyed
        population values in thousands.
    """
    try:
        data = await _hudud_get(f"/api/v1/passport/DemographyPopulationByYears/{soato}/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_population_by_gender_age(soato: str) -> str:
    """
    Get population breakdown by gender and age groups for a region from
    hudud.stat.uz (population pyramid data).

    Args:
        soato: SOATO code of the region, e.g. "1700" (national) or "1735".

    Returns:
        JSON object with:
          - "soato":       region code
          - "period":      reference year
          - "periodicity": frequency label (Uzbek)
          - "unit":        unit of measurement (e.g. "kishi" = persons)
          - "AGES":        list of age group labels (e.g. ["0-2", "3-5", ...])
          - "boysData":    population counts per age group for males
          - "girlsData":   population counts per age group for females
    """
    try:
        data = await _hudud_get(f"/api/v1/passport/PopularityGenderAges/{soato}/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_population_by_gender_subregion(soato: str) -> str:
    """
    Get male/female population split across all sub-regions of a region from
    hudud.stat.uz.

    Args:
        soato: SOATO code of the parent region, e.g. "1700" or "1735".

    Returns:
        JSON object with:
          - "soato":       parent region code
          - "period":      reference period
          - "unit":        unit (e.g. "ming kishi" = thousand persons)
          - "region_list": list of sub-region SOATO codes
          - "male_list":   male population for each sub-region (same order)
          - "female_list": female population for each sub-region (same order)
    """
    try:
        data = await _hudud_get(f"/api/v1/passport/PopularityGenderBySoato/{soato}/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_urban_rural_population(soato: str) -> str:
    """
    Get urban vs. rural population split for a region from hudud.stat.uz.

    Args:
        soato: SOATO code of the region, e.g. "1735".

    Returns:
        JSON object with "soato", "period", "unit", "cityData" (urban
        population), and "villageData" (rural population).
    """
    try:
        data = await _hudud_get(f"/api/v1/passport/PopulationVillageAndCityBySoato/{soato}/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_demography_indicators(soato: str) -> str:
    """
    Get quarterly demographic indicator time-series (births, deaths, etc.)
    for a region from hudud.stat.uz.

    Args:
        soato: SOATO code of the region, e.g. "1735".

    Returns:
        JSON object with available periods and a list of demographic indicator
        series. Each series has sdmx_id, multilingual title, unit, and
        "periods_data" — list of {year, period, value, growth_percentage}.
    """
    try:
        data = await _hudud_get(f"/api/v1/passport/demography/{soato}/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_import_export(soato: str) -> str:
    """
    Get monthly import and export trade data for a region from hudud.stat.uz.

    Args:
        soato: SOATO code of the region, e.g. "1735".

    Returns:
        JSON object with "soato", "period" (latest month), "unit" (currency),
        "Periods" (list of month codes like "2025-M04"), "Import" and "Export"
        (lists of cumulative values, same order as Periods).
    """
    try:
        data = await _hudud_get(f"/api/v1/passport/import-export/{soato}/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_salary_by_subregion(soato: str) -> str:
    """
    Get average wage data for all sub-regions of a region from hudud.stat.uz.

    Args:
        soato: SOATO code of the parent region, e.g. "1735".

    Returns:
        JSON object with "soato", "period", "unit", and "data" — list of
        {soato, value} pairs giving the average monthly wage per sub-region.
    """
    try:
        data = await _hudud_get(f"/api/v1/passport/SalaryBySoato/{soato}/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_salary_by_activity(activity_codes: str) -> str:
    """
    Get quarterly average wage time-series broken down by economic activity
    type (NACE codes) from hudud.stat.uz.

    Args:
        activity_codes: Comma-separated NACE section codes, e.g. "A,B,C".
                        Call hudud_list_activity_types to see all valid codes.

    Returns:
        JSON object with "codes", "period", and "data" — list of activity
        entries, each with classifier labels and a "data" list of
        {year, period, value} quarterly wage observations.
    """
    try:
        data = await _hudud_get(
            "/api/v1/passport/SalaryByActivityTypes/",
            {"codes": activity_codes},
        )
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_list_activity_types() -> str:
    """
    List all economic activity types (NACE sections) used in hudud.stat.uz.
    The codes returned can be used with hudud_get_salary_by_activity and
    hudud_get_org_count_by_activity.

    Returns:
        JSON array of activity type objects. Each has:
          - "code":    NACE section letter (e.g. "A", "B", "C")
          - "name":    name in Uzbek Latin
          - "name_ru": name in Russian
          - "name_en": name in English
    """
    try:
        data = await _hudud_get("/api/v1/passport/ActivityTypesList/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_org_count_by_activity() -> str:
    """
    Get the current count of registered organisations by economic activity
    type (NACE section) in Uzbekistan from hudud.stat.uz.

    Returns:
        JSON object with "period" (reference month, e.g. "2026-M04") and
        "results" — list of {code, name, name_ru, value, percentage} entries,
        where value is the total number of organisations and percentage is
        the year-on-year growth rate.
    """
    try:
        data = await _hudud_get("/api/v1/passport/OrgCountByActivityTypes/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_geometries() -> str:
    """
    Get GeoJSON feature geometries for all administrative regions of
    Uzbekistan from hudud.stat.uz. Suitable for interactive mapping.

    Returns:
        GeoJSON FeatureCollection where each feature represents an
        administrative region with:
          - "id":       SOATO code (string)
          - "geometry": MultiPolygon with lat/long coordinates
                        (WGS84, suitable for Leaflet/Mapbox)
          - "properties": currently empty in the raw API response
    """
    try:
        data = await _hudud_get("/api/v1/gis/geometries/")
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_sdmx_by_period_type(period_type: str = "annual") -> str:
    """
    Get a list of SDMX indicator metadata filtered by periodicity type from
    hudud.stat.uz. Useful for discovering which indicators are available at
    specific frequencies (annual, quarterly, monthly).

    Args:
        period_type: Periodicity filter — "annual", "quarterly", or "monthly".
                     Defaults to "annual".

    Returns:
        JSON object with "period_type" and "sdmx_list" — array of indicators
        with id, title (multilingual), unit, sdmx_id, and associated color
        coding for UI display.
    """
    try:
        data = await _hudud_get(
            "/api/v1/passport/FilterSDMXListByPeriodType/",
            {"period_type": period_type},
        )
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


@mcp.tool()
async def hudud_get_timeline_by_period(
    period_type: str = "annual",
    period: str = "",
) -> str:
    """
    Get a timeline of key economic indicators for a specific time period from
    hudud.stat.uz. Returns top trending indicators with their recent values
    and historical series.

    Args:
        period_type: "annual", "quarterly", or "monthly". Defaults to "annual".
        period:      Specific period, e.g. "2026", "2026-Q1", "2026-M03".
                     Leave empty for latest available.

    Returns:
        JSON object with "period_type", "period", and "timeline_data" — list
        of trending indicators, each with title (multilingual), unit, and a
        "timeline" list of {year, period, value} observations.
    """
    try:
        params = {"period_type": period_type}
        if period:
            params["period"] = period
        data = await _hudud_get("/api/v1/passport/TimelineByPeriodAndPeriodType/", params)
        return _dump_json(data)
    except Exception as e:
        return _dump_json({"error": str(e)})


if __name__ == "__main__":
    mcp.run()
