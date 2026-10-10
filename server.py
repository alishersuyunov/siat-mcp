"""
MCP Server for Uzbekistan official statistics.

Sources
-------
siat.stat.uz   - National Statistics Committee SIAT portal (JSON API)
nsdp.stat.uz   - National Summary Data Page, IMF DSBB-compliant (SDMX 2.1 XML)
SIAT Catalog API: GET https://siat.stat.uz/api/sdmx/json/
SIAT Data API:    GET https://siat.stat.uz/media/uploads/sdmx/sdmx_data_{id}.json
NSDP data:        static SDMX 2.1 XML files hosted on stat.uz, cbu.uz, api.mf.uz, uzse.uz
"""

import asyncio
import json
import os
import re
import threading
import unicodedata
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
    import simdjson
    _SIMDJSON = True
    _SIMDJSON_PARSER = simdjson.Parser()
    _SIMDJSON_LOCK = threading.Lock()
except ImportError:
    _SIMDJSON = False
    _SIMDJSON_PARSER = None
    _SIMDJSON_LOCK = None

try:
    from asyncache import cached
    from cachetools import TTLCache
    _CACHE = True
except ImportError:
    _CACHE = False

_PERIOD_RE = re.compile(r"^(\d{4})(?:-Q[1-4]|-M(?:0[1-9]|1[0-2]))?$")

SIAT_BASE = "https://siat.stat.uz"
SIAT_API_BASE = "https://api.siat.stat.uz"
# HUDUD_BASE = "https://hudud.stat.uz"

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


def _legacy_tool():
    """Keep detailed tools available without crowding the default MCP menu."""
    return mcp.tool() if os.environ.get("SIAT_MCP_LEGACY_TOOLS") == "1" else lambda func: func


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_name(item: dict, lang: str = "en") -> str:
    for key in (f"name_{lang}", "name_en", "name_uz", "name"):
        value = item.get(key)
        if value:
            return value
    return str(item.get("id", "unknown"))


def _flatten_catalog(nodes: list[dict], lang: str = "en") -> list[dict]:
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
    nodes: list[dict], query: str, lang: str = "en", path: str = "",
) -> list[dict]:
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
    for node in nodes:
        if node.get("id") == target_id:
            return node
        children = node.get("children") or []
        found = _find_by_id(children, target_id)
        if found:
            return found
    return None


def _find_by_code(nodes: list[dict], target_code: str) -> dict | None:
    for node in nodes:
        if str(node.get("code") or "").lower() == target_code.lower():
            return node
        children = node.get("children") or []
        found = _find_by_code(children, target_code)
        if found:
            return found
    return None


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _period_year(value: str) -> int | None:
    match = _PERIOD_RE.fullmatch(value)
    return int(match.group(1)) if match else None


def _period_sort_key(value: str) -> tuple[int, int, int]:
    year = int(value[:4])
    if "-M" in value:
        return year, int(value[-2:]), 0
    if "-Q" in value:
        return year, int(value[-1]) * 3, 1
    return year, 12, 2


def _localized_metadata(fields: list[dict], lang: str) -> list[dict]:
    name_key = f"name_{lang}"
    value_key = f"value_{lang}"
    return [
        {
            **({"key": field["key_name"]} if field.get("key_name") else {}),
            "name": field.get(name_key) or field.get("name_en") or field.get("name_uz", ""),
            "value": field.get(value_key) or field.get("value_en") or field.get("value_uz"),
        }
        for field in fields
    ]


_SEARCH_STOPWORDS = {
    "a", "about", "and", "by", "data", "during", "for", "from", "get", "give",
    "in", "is", "latest", "me", "of", "on", "please", "show", "since", "statistics",
    "the", "to", "trend", "what", "with", "year",
}


def _normalize_search(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _catalog_matches(catalog: list[dict], query: str, lang: str, limit: int) -> list[dict]:
    phrase = _normalize_search(query)
    phrase = re.sub(r"\bgdp\b", "gross domestic product", phrase)
    phrase = re.sub(r"\bcpi\b", "consumer price index", phrase)
    tokens = [
        word for word in phrase.split()
        if word not in _SEARCH_STOPWORDS and not re.fullmatch(r"\d{4}", word)
    ]
    if not tokens:
        return []
    search_phrase = " ".join(tokens)

    matches: list[dict] = []

    def visit(nodes: list[dict], path: list[str]) -> None:
        for node in nodes:
            name = _get_name(node, lang)
            current_path = [*path, name]
            children = node.get("children") or []
            if children:
                visit(children, current_path)
                continue
            names = [
                _normalize_search(node.get(key) or "")
                for key in ("name_en", "name_uz", "name_ru", "name_uzc")
            ]
            path_text = _normalize_search(" ".join(current_path[:-1]))
            name_score = max(
                (100 if search_phrase == text else 35 if search_phrase in text else 0)
                + 6 * sum(token in text.split() for token in tokens)
                for text in names
            )
            path_score = sum(token in path_text.split() for token in tokens)
            score = name_score + path_score
            if score <= 0:
                continue
            matches.append({
                "id": node.get("id"),
                "code": node.get("code"),
                "name": name,
                "path": " > ".join(current_path),
                "frequency": node.get("period"),
                "_score": score,
            })

    visit(catalog, [])
    matches.sort(key=lambda item: (-item["_score"], item["name"], item["id"] or 0))
    return matches[:limit]


def _public_match(match: dict) -> dict:
    return {key: value for key, value in match.items() if key != "_score"}


def _json(obj: Any) -> str:
    if _ORJSON:
        return orjson.dumps(obj).decode()
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _format_dataset(
    dataset_id: int,
    obj: dict,
    lang: str = "en",
    *,
    include_metadata: bool = True,
    start_year: int | None = None,
    end_year: int | None = None,
) -> dict:
    metadata_raw: list[dict] = obj["metadata"]
    data_raw: list[dict] = obj["data"]

    metadata = _localized_metadata(metadata_raw, lang)

    klassif_key = f"Klassifikator_{lang}" if lang != "uz" else "Klassifikator"
    data: list[dict[str, Any]] = []
    for row in data_raw:
        record: dict[str, Any] = {"code": row.get("Code", "")}
        label = (
            row.get(klassif_key)
            or row.get("Klassifikator_en")
            or row.get("Klassifikator")
            or ""
        )
        record["classifier"] = label
        record["region"] = label  # Backward-compatible alias.
        for k, v in row.items():
            year = _period_year(k)
            if year is None:
                continue
            if start_year is not None and year < start_year:
                continue
            if end_year is not None and year > end_year:
                continue
            record[k] = v
        data.append(record)

    period_keys = sorted(
        {k for row in data for k in row if _period_year(k) is not None},
        key=_period_sort_key,
    )
    years = sorted({int(k[:4]) for k in period_keys})
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
        "id": dataset_id,
        "indicator": indicator,
        "unit": unit,
        "years": f"{years[0]}-{years[-1]}" if years else "unknown",
        "periods": f"{period_keys[0]} to {period_keys[-1]}" if period_keys else "unknown",
        "num_regions": len(data),
        "num_rows": len(data),
        "source_url": f"{SIAT_BASE}/media/uploads/sdmx/sdmx_data_{dataset_id}.json",
    }

    result: dict[str, Any] = {"summary": summary, "data": data}
    if include_metadata:
        result["metadata"] = metadata
    return result


def _parse_sdmx_xml(content: bytes) -> dict:
    def _local(tag: str) -> str:
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
# HTTP Clients
# ---------------------------------------------------------------------------

def _make_client(base_url: str, *, xml: bool = False) -> httpx.AsyncClient:
    if xml:
        headers = {"accept": "application/xml, text/xml, */*",
                    "accept-language": "en", "user-agent": "siat-mcp/1.0"}
    else:
        headers = {"accept": "application/json, text/plain, */*",
                    "accept-language": "uz",
                    "origin": base_url, "referer": f"{base_url}/"}
    return httpx.AsyncClient(
        headers=headers, timeout=60.0, follow_redirects=True,
    )


_clients: dict[str, httpx.AsyncClient] = {}

def _client(key: str, base_url: str = "", *, xml: bool = False) -> httpx.AsyncClient:
    if key not in _clients:
        _clients[key] = _make_client(base_url or key, xml=xml)
    return _clients[key]


def _parse_json(r: httpx.Response) -> Any:
    if _SIMDJSON and _SIMDJSON_PARSER is not None and _SIMDJSON_LOCK is not None:
        with _SIMDJSON_LOCK:
            return _SIMDJSON_PARSER.parse(r.content, recursive=True)
    return orjson.loads(r.content) if _ORJSON else r.json()


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

async def _fetch_catalog() -> list[dict]:
    r = await _client("siat", SIAT_BASE).get(f"{SIAT_BASE}/api/sdmx/json/")
    r.raise_for_status()
    return _parse_json(r)


async def _fetch_dataset(dataset_id: int) -> dict:
    url = f"{SIAT_BASE}/media/uploads/sdmx/sdmx_data_{dataset_id}.json"
    r = await _client("siat", SIAT_BASE).get(url)
    r.raise_for_status()
    raw = _parse_json(r)
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if not isinstance(raw, dict) or "metadata" not in raw or "data" not in raw:
        raise ValueError(f"Unexpected dataset format: {str(raw)[:200]}")
    return raw


async def _siat_api_get(path: str) -> Any:
    r = await _client("siat_api", SIAT_BASE).get(f"{SIAT_API_BASE}{path}")
    r.raise_for_status()
    return _parse_json(r)


async def _fetch_dataset_info(dataset_id: int) -> dict:
    raw = await _siat_api_get(f"/sdmx/{dataset_id}/")
    if not isinstance(raw, dict) or raw.get("id") != dataset_id:
        raise ValueError("Unexpected dataset detail format")
    return raw


async def _fetch_dataset_metadata(dataset_id: int) -> list[dict]:
    raw = await _siat_api_get(f"/sdmx/{dataset_id}/metadata/")
    if not isinstance(raw, dict) or not isinstance(raw.get("meta_data"), list):
        raise ValueError("Unexpected dataset metadata format")
    return raw["meta_data"]


async def _fetch_dataset_table(dataset_id: int) -> list[dict]:
    raw = await _siat_api_get(f"/sdmx/{dataset_id}/table/")
    if not isinstance(raw, list):
        raise ValueError("Unexpected dataset table format")
    return raw


async def _fetch_portal_counters() -> dict:
    raw = await _siat_api_get("/common/counters/")
    if not isinstance(raw, dict):
        raise ValueError("Unexpected portal counters format")
    return raw


async def _fetch_nsdp_xml(url: str) -> bytes:
    r = await _client("nsdp", xml=True).get(url)
    r.raise_for_status()
    return r.content


# async def _hudud_get(path: str, params: dict | None = None) -> Any:
#     r = await _client("hudud", HUDUD_BASE).get(f"{HUDUD_BASE}{path}", params=params)
#     r.raise_for_status()
#     return _parse_json(r)
#
#
# async def _hudud_regions() -> list:
#     return await _hudud_get("/api/v1/gis/regions/", {"show_children": "true"})
#
#
# async def _hudud_spheres() -> list:
#     return await _hudud_get("/api/v1/gis/spheres/")
#
#
# async def _hudud_activity_types() -> list:
#     return await _hudud_get("/api/v1/passport/ActivityTypesList/")


if _CACHE:
    _fetch_catalog = cached(cache=TTLCache(maxsize=1, ttl=3600))(_fetch_catalog)
    _fetch_dataset = cached(cache=TTLCache(maxsize=32, ttl=3600))(_fetch_dataset)
    _fetch_dataset_info = cached(cache=TTLCache(maxsize=128, ttl=3600))(_fetch_dataset_info)
    _fetch_dataset_metadata = cached(cache=TTLCache(maxsize=128, ttl=3600))(_fetch_dataset_metadata)
    _fetch_dataset_table = cached(cache=TTLCache(maxsize=16, ttl=3600))(_fetch_dataset_table)
    _fetch_portal_counters = cached(cache=TTLCache(maxsize=1, ttl=3600))(_fetch_portal_counters)
    _fetch_nsdp_xml = cached(cache=TTLCache(maxsize=10, ttl=6 * 3600))(_fetch_nsdp_xml)
    # _hudud_regions = cached(cache=TTLCache(maxsize=1, ttl=3600))(_hudud_regions)
    # _hudud_spheres = cached(cache=TTLCache(maxsize=1, ttl=3600))(_hudud_spheres)
    # _hudud_activity_types = cached(cache=TTLCache(maxsize=1, ttl=3600))(_hudud_activity_types)


# ---------------------------------------------------------------------------
# siat.stat.uz tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def siat_query(
    request: str,
    classifier: str = "",
    period: str = "latest",
    start_year: int = 0,
    end_year: int = 0,
    lang: str = "en",
    max_rows: int = 15,
    max_periods: int = 12,
) -> str:
    """Find and retrieve SIAT statistics in one call.

    Pass an indicator description, exact catalog code, or numeric dataset ID
    as request. A clear match returns compact data with units, notes, source,
    and alternatives. An ambiguous request returns five named choices; call
    this tool again with the chosen ID. Defaults to the latest period. For a
    trend, set period="all" and optionally start_year/end_year. Use classifier
    for a region, country, sector, or classifier code. No catalog browsing is
    needed before calling this tool.
    """
    request = request.strip()
    if not request:
        return _json({"status": "error", "message": "Describe an indicator or provide its dataset ID/code."})
    if lang not in {"en", "uz", "ru", "uzc"}:
        return _json({"status": "error", "message": "lang must be en, uz, ru, or uzc"})
    if not 1 <= max_rows <= 100 or not 1 <= max_periods <= 120:
        return _json({"status": "error", "message": "max_rows must be 1-100 and max_periods 1-120"})
    if start_year and end_year and start_year > end_year:
        return _json({"status": "error", "message": "start_year must not exceed end_year"})

    selected: dict | None = None
    alternatives: list[dict] = []
    id_in_request = re.search(r"\b(?:dataset|id)\s*#?:?\s*(\d+)\b", request, re.IGNORECASE)
    if request.isdecimal() or id_in_request:
        dataset_id = int(request if request.isdecimal() else id_in_request.group(1))
    else:
        try:
            catalog = await _fetch_catalog()
        except Exception as exc:
            return _json({"status": "error", "message": f"Catalog unavailable: {exc}"})

        node = _find_by_code(catalog, request)
        if node is not None:
            if node.get("children"):
                leaves = _flatten_catalog([node], lang)
                return _json({
                    "status": "choose_dataset",
                    "message": "This code names a category. Choose a leaf dataset ID.",
                    "matches": leaves[:5],
                    "more_matches": len(leaves) > 5,
                })
            dataset_id = node["id"]
            selected = {
                "id": node["id"], "code": node.get("code"),
                "name": _get_name(node, lang), "frequency": node.get("period"),
            }
        else:
            matches = _catalog_matches(catalog, request, lang, 6)
            if not matches:
                return _json({"status": "not_found", "query": request,
                              "message": "No matching indicator. Try a shorter indicator name or dataset code."})
            top = matches[0]
            next_score = matches[1]["_score"] if len(matches) > 1 else 0
            clear_match = len(matches) == 1 or (top["_score"] >= 100 and top["_score"] - next_score >= 10)
            if not clear_match:
                return _json({
                    "status": "choose_dataset",
                    "query": request,
                    "message": "Several indicators match. Call siat_query with the chosen ID or code.",
                    "matches": [_public_match(match) for match in matches[:5]],
                    "more_matches": len(matches) > 5,
                })
            dataset_id = top["id"]
            selected = _public_match(top)
            alternatives = [_public_match(match) for match in matches[1:4]]

    if not isinstance(dataset_id, int) or dataset_id <= 0:
        return _json({"status": "error", "message": "Invalid dataset ID."})

    try:
        raw = await _fetch_dataset(dataset_id)
    except Exception as exc:
        return _json({"status": "error", "dataset_id": dataset_id,
                      "message": f"Dataset unavailable: {exc}"})

    metadata = _localized_metadata(raw["metadata"], lang)
    def metadata_value(*terms: str) -> Any:
        return next(
            (localized["value"] for source, localized in zip(raw["metadata"], metadata, strict=True)
             if any(term in (source.get("name_en") or source.get("key_name") or "").casefold()
                    for term in terms)),
            None,
        )

    requested_classifier = _normalize_search(classifier)
    all_rows = raw["data"]
    matched_rows = [
        row for row in all_rows
        if not requested_classifier
        or requested_classifier == _normalize_search(str(row.get("Code", "")))
        or any(
            requested_classifier in _normalize_search(str(row.get(key) or ""))
            for key in ("Klassifikator", "Klassifikator_en", "Klassifikator_ru", "Klassifikator_uzc")
        )
    ]
    if not matched_rows:
        return _json({
            "status": "classifier_not_found", "dataset_id": dataset_id,
            "classifier": classifier,
            "available_classifiers": [
                {"code": row.get("Code"), "name": row.get(f"Klassifikator_{lang}") or row.get("Klassifikator_en") or row.get("Klassifikator")}
                for row in all_rows[:20]
            ],
        })

    available_periods = sorted(
        {key for row in matched_rows for key, value in row.items()
         if _period_year(key) is not None and value is not None},
        key=_period_sort_key,
    )
    bounded_periods = [
        key for key in available_periods
        if (not start_year or int(key[:4]) >= start_year)
        and (not end_year or int(key[:4]) <= end_year)
    ]
    requested_period = period.strip()
    if requested_period == "latest":
        wants_trend = bool(re.search(r"\b(?:trend|history|historical|time series|over time)\b", request, re.IGNORECASE))
        since_year = re.search(r"\b(?:since|from)\s+((?:19|20)\d{2})\b", request, re.IGNORECASE)
        dates_in_request = re.findall(r"\b(?:19|20)\d{2}(?:-Q[1-4]|-M(?:0[1-9]|1[0-2]))?\b", request)
        if len(dates_in_request) == 1 and since_year:
            bounded_periods = [key for key in bounded_periods if int(key[:4]) >= int(since_year.group(1))]
            requested_period = "all"
        elif len(dates_in_request) == 1 and wants_trend:
            bounded_periods = [key for key in bounded_periods if int(key[:4]) == int(dates_in_request[0][:4])]
            requested_period = "all"
        elif len(dates_in_request) == 1 and not wants_trend:
            requested_period = dates_in_request[0]
        elif len(dates_in_request) >= 2:
            start = min(int(value[:4]) for value in dates_in_request)
            end = max(int(value[:4]) for value in dates_in_request)
            bounded_periods = [key for key in bounded_periods if start <= int(key[:4]) <= end]
            requested_period = "all"
        elif wants_trend:
            requested_period = "all"
    if requested_period == "latest":
        returned_periods = bounded_periods[-1:]
    elif requested_period == "all":
        returned_periods = bounded_periods[-max_periods:]
    elif _period_year(requested_period) is not None:
        returned_periods = [requested_period] if requested_period in bounded_periods else []
    else:
        return _json({"status": "error", "message": "period must be latest, all, YYYY, YYYY-Q1..Q4, or YYYY-M01..M12"})
    if not returned_periods:
        return _json({"status": "period_not_found", "dataset_id": dataset_id,
                      "requested_period": requested_period,
                      "available_periods": available_periods[-12:]})

    label_key = f"Klassifikator_{lang}" if lang != "uz" else "Klassifikator"
    rows = [
        {
            "code": row.get("Code"),
            "classifier": row.get(label_key) or row.get("Klassifikator_en") or row.get("Klassifikator"),
            "values": {key: row.get(key) for key in returned_periods if key in row},
        }
        for row in matched_rows[:max_rows]
    ]
    return _json({
        "status": "ok",
        "dataset": {
            "id": dataset_id,
            "code": selected.get("code") if selected else metadata_value("identification number", "identification code"),
            "name": metadata_value("indicator name", "data set name") or (selected.get("name") if selected else None),
            "unit": metadata_value("unit"),
            "frequency": metadata_value("periodicity") or (selected.get("frequency") if selected else None),
            "last_modified": metadata_value("last modified date"),
            "notes": [localized["value"] for source, localized in zip(raw["metadata"], metadata, strict=True)
                      if "note" in (source.get("name_en") or source.get("key_name") or "").casefold()],
            "source_url": f"{SIAT_BASE}/media/uploads/sdmx/sdmx_data_{dataset_id}.json",
        },
        "match": selected,
        "alternatives": alternatives,
        "available_period_range": [available_periods[0], available_periods[-1]] if available_periods else [],
        "periods_returned": returned_periods,
        "periods_truncated": requested_period == "all" and len(bounded_periods) > max_periods,
        "total_classifiers": len(matched_rows),
        "classifiers_truncated": len(matched_rows) > max_rows,
        "rows": rows,
    })


@_legacy_tool()
async def list_categories(lang: str = "en") -> str:
    """
    List the top-level statistical categories from the siat.stat.uz catalog.

    Args:
        lang: Language for names - "en", "uz", "ru", "uzc". Defaults to "en".

    Returns:
        JSON array of top-level categories with their id, name, code, and
        number of child items.
    """
    try:
        catalog = await _fetch_catalog()
    except Exception as e:
        return _json({"error": str(e)})
    return _json(_top_level_summary(catalog, lang))


@_legacy_tool()
async def search_catalog(query: str, lang: str = "en") -> str:
    """
    Search the siat.stat.uz data catalog for datasets or categories matching
    a keyword or phrase.

    Args:
        query: Keyword or phrase to search for (case-insensitive).
        lang:  Language to search in - "en", "uz", "ru", "uzc". Defaults "en".

    Returns:
        JSON array of matching items with id, name, code, path in the catalog
        hierarchy, whether they have children, period, updated_at, and status.
        Items without children are leaf datasets (directly retrievable).
    """
    try:
        catalog = await _fetch_catalog()
    except Exception as e:
        return _json({"error": str(e)})
    results = _search_tree(catalog, query, lang)
    if not results:
        return _json({"message": f"No results found for '{query}'."})
    return _json(results)


@_legacy_tool()
async def get_category(category_id: int, lang: str = "en") -> str:
    """
    Get the contents of a specific category by its id, showing its immediate
    children (sub-categories or datasets).

    Args:
        category_id: The numeric id of the category (from list_categories or
                     search_catalog).
        lang: Language for names - "en", "uz", "ru", "uzc". Defaults "en".

    Returns:
        JSON object with the category name and a "children" array. Each child
        includes id, name, code, has_children flag, period, updated_at, status.
        Children without sub-children are leaf datasets. If multiple leaf
        datasets are present, use the returned bulk_fetch hint with get_datasets.
    """
    try:
        catalog = await _fetch_catalog()
    except Exception as e:
        return _json({"error": str(e)})

    node = _find_by_id(catalog, category_id)
    if node is None:
        return _json({"error": f"Category {category_id} not found."})

    children = node.get("children") or []
    leaf_child_ids = [
        str(c.get("id"))
        for c in children
        if not c.get("children") and c.get("id") is not None
    ]
    bulk_fetch = None
    if len(leaf_child_ids) > 1:
        bulk_fetch = {
            "tool": "get_datasets",
            "dataset_ids": ",".join(leaf_child_ids),
            "note": "Use this when fetching multiple children from this category.",
        }
    return _json({
        "id": node.get("id"),
        "name": _get_name(node, lang),
        "code": node.get("code"),
        "bulk_fetch": bulk_fetch,
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
    })


@_legacy_tool()
async def list_datasets(lang: str = "en") -> str:
    """
    Return a flat list of all leaf datasets in the siat.stat.uz catalog
    (i.e. every entry that has actual data, not just sub-categories).

    Args:
        lang: Language for names - "en", "uz", "ru", "uzc". Defaults "en".

    Returns:
        JSON array of datasets. Each item has id, name (in requested language),
        name_uz, name_ru, name_en, code, period, updated_at, status.
        Use the id with get_dataset to retrieve the actual data.
    """
    try:
        catalog = await _fetch_catalog()
    except Exception as e:
        return _json({"error": str(e)})
    return _json(_flatten_catalog(catalog, lang))


@_legacy_tool()
async def get_dataset(dataset_id: int, lang: str = "en") -> str:
    """
    Retrieve statistical data for a specific dataset from siat.stat.uz.
    If two or more dataset ids/codes are known, use get_datasets instead of
    calling this tool repeatedly.

    Args:
        dataset_id: Numeric id of the dataset (obtain from search_catalog,
                    get_category, or list_datasets).
        lang:       Language for labels - "en", "uz", "ru", "uzc". Default "en".

    Returns:
        JSON object with:
          - "metadata": list of field descriptors (indicator name, unit,
            periodicity, source, etc.) in the requested language.
          - "data": list of observation records. Each contains a classifier
            label, its legacy region alias, and annual/quarterly/monthly values.
          - "summary": indicator name, unit, period range, row count, and
            source URL. num_regions remains as a backward-compatible alias.
    """
    try:
        obj = await _fetch_dataset(dataset_id)
    except Exception as e:
        return _json({"error": str(e)})
    return _json(_format_dataset(dataset_id, obj, lang, include_metadata=True))


@_legacy_tool()
async def get_dataset_info(dataset_id: int, lang: str = "en") -> str:
    """Get a SIAT dataset's name, catalog code, frequency, classifier type,
    update timestamp, status, and source links without downloading its table.
    The classifier type distinguishes territories from sectors and other rows.
    """
    try:
        item = await _fetch_dataset_info(dataset_id)
    except Exception as e:
        return _json({"error": str(e)})

    classifier = item.get("classifier") or {}
    return _json({
        "id": item["id"],
        "name": _get_name(item, lang),
        "code": item.get("code"),
        "period": item.get("period"),
        "classifier": {
            "id": classifier.get("id"),
            "name": _get_name(classifier, lang) if classifier else None,
        },
        "updated_xlsx": item.get("updated_xlsx"),
        "status": item.get("status"),
        "is_active": item.get("is_active"),
        "source_url": f"{SIAT_API_BASE}/sdmx/{dataset_id}/",
        "dataset_url": f"{SIAT_BASE}/reports-filed/{dataset_id}/table-data",
    })


@_legacy_tool()
async def get_dataset_table(
    dataset_id: int,
    lang: str = "en",
    classifier_ids: str = "",
    periods: str = "",
    start_year: int = 0,
    end_year: int = 0,
    max_rows: int = 10,
) -> str:
    """Read the SIAT table API, preserving classifier IDs and root flags.

    Filter with comma-separated classifier IDs or exact periods (for example
    "2025,2026-Q1"). Results include at most max_rows classifiers (1-100),
    with total_rows and truncated so the LLM can see whether rows were omitted.
    """
    if not 1 <= max_rows <= 100:
        return _json({"error": "max_rows must be between 1 and 100"})
    if start_year and end_year and start_year > end_year:
        return _json({"error": "start_year must not exceed end_year"})
    try:
        requested_ids = {int(value) for value in _split_csv(classifier_ids)}
    except ValueError:
        return _json({"error": "classifier_ids must be comma-separated integers"})
    requested_periods = set(_split_csv(periods))
    if any(_period_year(period) is None for period in requested_periods):
        return _json({"error": "periods must use YYYY, YYYY-Q1..Q4, or YYYY-M01..M12"})

    try:
        raw = await _fetch_dataset_table(dataset_id)
    except Exception as e:
        return _json({"error": str(e)})

    selected = [row for row in raw if not requested_ids or row.get("id") in requested_ids]
    result_rows: list[dict] = []
    for row in selected[:max_rows]:
        values: dict[str, Any] = {}
        for point in row.get("data") or []:
            if not isinstance(point, dict):
                continue
            for period, value in point.items():
                year = _period_year(period)
                if year is None or (requested_periods and period not in requested_periods):
                    continue
                if start_year and year < start_year:
                    continue
                if end_year and year > end_year:
                    continue
                values[period] = value
        result_rows.append({
            "classifier_id": row.get("id"),
            "classifier": _get_name(row, lang),
            "is_root": row.get("is_root"),
            "map_code": row.get("map_code"),
            "values": dict(sorted(values.items(), key=lambda item: _period_sort_key(item[0]))),
        })

    return _json({
        "dataset_id": dataset_id,
        "total_rows": len(selected),
        "returned_rows": len(result_rows),
        "truncated": len(selected) > max_rows,
        "source_url": f"{SIAT_API_BASE}/sdmx/{dataset_id}/table/",
        "rows": result_rows,
    })


@_legacy_tool()
async def get_portal_counters() -> str:
    """Get SIAT portal totals such as indicators, SDMX items, and downloads."""
    try:
        return _json(await _fetch_portal_counters())
    except Exception as e:
        return _json({"error": str(e)})


@_legacy_tool()
async def get_datasets(
    dataset_ids: str = "",
    dataset_codes: str = "",
    lang: str = "en",
    include_metadata: bool = False,
    start_year: int = 0,
    end_year: int = 0,
) -> str:
    """
    Retrieve multiple siat.stat.uz datasets in one MCP tool call. Prefer this
    whenever two or more dataset ids/codes are known.

    Args:
        dataset_ids: Comma-separated numeric dataset ids, e.g. "544,548,582".
        dataset_codes: Comma-separated leaf catalog codes, e.g.
                       "1.01.01.0001,1.01.01.0002".
        lang: Language for labels - "en", "uz", "ru", "uzc".
        include_metadata: Include metadata fields for every dataset. Defaults
                          false to reduce token usage in bulk calls.
        start_year: Optional first year to include in observations. Use 0 for
                    no lower bound.
        end_year: Optional last year to include in observations. Use 0 for no
                  upper bound.

    Returns:
        JSON object with a datasets array. Each item contains summary and data,
        plus metadata when include_metadata=true. Use this instead of repeated
        get_dataset calls when you already know several ids or catalog codes.
    """
    ids: list[int] = []
    errors: list[dict[str, str]] = []

    for raw_id in _split_csv(dataset_ids):
        try:
            ids.append(int(raw_id))
        except ValueError:
            errors.append({"dataset_id": raw_id, "error": "dataset_ids must be integers"})

    codes = _split_csv(dataset_codes)
    if codes:
        try:
            catalog = await _fetch_catalog()
        except Exception as e:
            return _json({"error": str(e)})
        for code in codes:
            node = _find_by_code(catalog, code)
            if node is None:
                errors.append({"dataset_code": code, "error": "code not found"})
                continue
            if node.get("children"):
                errors.append({"dataset_code": code, "error": "code is a category, not a leaf dataset"})
                continue
            node_id = node.get("id")
            if isinstance(node_id, int):
                ids.append(node_id)
            else:
                errors.append({"dataset_code": code, "error": "dataset id missing"})

    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        return _json({
            "error": "Provide at least one dataset id or leaf dataset code.",
            "errors": errors,
        })

    fetched = await asyncio.gather(
        *(_fetch_dataset(dataset_id) for dataset_id in unique_ids),
        return_exceptions=True,
    )

    datasets: list[dict] = []
    for dataset_id, obj in zip(unique_ids, fetched, strict=True):
        if isinstance(obj, Exception):
            errors.append({"dataset_id": str(dataset_id), "error": str(obj)})
            continue
        datasets.append(_format_dataset(
            dataset_id,
            obj,
            lang,
            include_metadata=include_metadata,
            start_year=start_year or None,
            end_year=end_year or None,
        ))

    return _json({"count": len(datasets), "datasets": datasets, "errors": errors})


@_legacy_tool()
async def get_dataset_metadata(dataset_id: int, lang: str = "en") -> str:
    """
    Retrieve only the metadata (field descriptions) of a dataset - indicator
    name, unit of measurement, periodicity, data source.

    This uses SIAT's dedicated metadata endpoint, so the observation table
    does not need to be downloaded for a preview. The downloadable JSON may
    contain additional publication fields; get_dataset includes those.

    Args:
        dataset_id: Numeric id of the dataset.
        lang:       Language - "en", "uz", "ru", "uzc". Default "en".

    Returns:
        JSON array of metadata fields with key (when available), name, value.
    """
    try:
        fields = await _fetch_dataset_metadata(dataset_id)
    except Exception as e:
        return _json({"error": str(e)})
    return _json(_localized_metadata(fields, lang))


# ---------------------------------------------------------------------------
# nsdp.stat.uz tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def nsdp_list_datasets() -> str:
    """
    List all 22 datasets available on nsdp.stat.uz - Uzbekistan's National
    Summary Data Page (IMF DSBB-compliant macroeconomic statistics). No
    network request is made; the catalog is static.

    Returns:
        JSON array of dataset entries. Each entry contains:
          - "code":    Short IMF/SDMX identifier (e.g. "NAG", "CPI", "BOP").
          - "name":    Human-readable dataset name in English.
          - "freq":    Publication frequency - "A" (annual), "M" (monthly),
                       "Q" (quarterly), or combinations like "A/Q".
          - "xml_url": Direct URL to the SDMX 2.1 XML file.
          - "source":  Hosting domain (stat.uz, cbu.uz, api.mf.uz, uzse.uz).
        Pass "code" to nsdp_get_dataset to retrieve the actual time-series data.
    """
    return _json([
        {
            "code": code,
            "name": meta["name"],
            "freq": meta["freq"],
            "xml_url": meta["xml_url"],
            "source": meta["xml_url"].split("/")[2],
        }
        for code, meta in NSDP_CATALOG.items()
    ])


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
          - "dataset": descriptive metadata - name, code, prepared timestamp,
                       reporting_period, freq, xml_url, source domain.
          - "series":  list of time series. Each series contains:
              - "indicator":    SDMX INDICATOR dimension code.
              - "freq":         Frequency code ("A", "Q", or "M").
              - "unit_mult":    Integer scale exponent (0 = units, 6 = millions,
                                9 = billions), or null if not present.
              - "dimensions":   All SDMX dimension attributes as key/value pairs.
              - "observations": list of {time_period, value} dicts.
    """
    code = indicator_code.strip().upper()
    if code not in NSDP_CATALOG:
        available = ", ".join(sorted(NSDP_CATALOG))
        return _json({"error": f"Unknown indicator code '{code}'. Available: {available}"})

    meta = NSDP_CATALOG[code]
    url = meta["xml_url"]
    try:
        content = await _fetch_nsdp_xml(url)
    except httpx.HTTPStatusError as exc:
        return _json({"error": f"HTTP {exc.response.status_code} fetching {url}"})
    except httpx.RequestError as exc:
        return _json({"error": f"Network error fetching {url}: {exc}"})

    try:
        parsed = _parse_sdmx_xml(content)
    except ValueError as exc:
        return _json({"error": str(exc)})

    return _json({
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
# hudud.stat.uz — Regional Statistics Portal (disabled)
# ---------------------------------------------------------------------------
#
# @mcp.tool()
# async def hudud_list_regions(parent_soato: str = “”) -> str:
#     try:
#         if parent_soato:
#             data = await _hudud_get(“/api/v1/gis/regions/”, {“parent__isnull”: “false”, “parent_soato”: parent_soato})
#         else:
#             data = await _hudud_regions()
#         return _json(data)
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_list_spheres() -> str:
#     try:
#         data = await _hudud_spheres()
#         return _json([{“id”: s.get(“id”), “title”: s.get(“title”), “title_en”: s.get(“title_en”), “title_ru”: s.get(“title_ru”)} for s in data])
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_sphere_indicators(sphere_id: int) -> str:
#     try:
#         data = await _hudud_get(“/api/v1/gis/spheres/sdmx/”, {“menu”: sphere_id})
#         return _json([{“id”: ind.get(“id”), “title_en”: ind.get(“title_en”), “title_uz”: ind.get(“title_uz”) or ind.get(“title”), “title_ru”: ind.get(“title_ru”), “code”: ind.get(“code”), “sdmx_id”: ind.get(“sdmx_id”), “period_en”: ind.get(“period_en”), “unit_en”: ind.get(“unit_en”)} for ind in data])
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_indicator_periods(indicator_id: int) -> str:
#     try:
#         return _json(await _hudud_get(f”/api/v1/gis/sdmx/{indicator_id}/periods/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_indicator_data(indicator_id: int, soato: str = “”, period: str = “”) -> str:
#     try:
#         return _json(await _hudud_get(f”/api/v1/gis/sdmx/{indicator_id}/”, {“soato”: soato, “period”: period}))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_indicator_metadata(indicator_id: int) -> str:
#     try:
#         return _json(await _hudud_get(f”/api/v1/gis/sdmx-info/{indicator_id}/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_region_passport(soato: str = “”) -> str:
#     try:
#         params = {“code”: soato} if soato else {}
#         return _json(await _hudud_get(“/api/v1/passport/MacroEconomicAndDemographicIndicators/”, params))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_population_by_years(soato: str) -> str:
#     try:
#         return _json(await _hudud_get(f”/api/v1/passport/DemographyPopulationByYears/{soato}/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_population_by_gender_age(soato: str) -> str:
#     try:
#         return _json(await _hudud_get(f”/api/v1/passport/PopularityGenderAges/{soato}/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_population_by_gender_subregion(soato: str) -> str:
#     try:
#         return _json(await _hudud_get(f”/api/v1/passport/PopularityGenderBySoato/{soato}/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_urban_rural_population(soato: str) -> str:
#     try:
#         return _json(await _hudud_get(f”/api/v1/passport/PopulationVillageAndCityBySoato/{soato}/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_demography_indicators(soato: str) -> str:
#     try:
#         return _json(await _hudud_get(f”/api/v1/passport/demography/{soato}/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_import_export(soato: str) -> str:
#     try:
#         return _json(await _hudud_get(f”/api/v1/passport/import-export/{soato}/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_salary_by_subregion(soato: str) -> str:
#     try:
#         return _json(await _hudud_get(f”/api/v1/passport/SalaryBySoato/{soato}/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_salary_by_activity(activity_codes: str) -> str:
#     try:
#         return _json(await _hudud_get(“/api/v1/passport/SalaryByActivityTypes/”, {“codes”: activity_codes}))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_list_activity_types() -> str:
#     try:
#         return _json(await _hudud_activity_types())
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_org_count_by_activity() -> str:
#     try:
#         return _json(await _hudud_get(“/api/v1/passport/OrgCountByActivityTypes/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_geometries() -> str:
#     try:
#         return _json(await _hudud_get(“/api/v1/gis/geometries/”))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_sdmx_by_period_type(period_type: str = “annual”) -> str:
#     try:
#         return _json(await _hudud_get(“/api/v1/passport/FilterSDMXListByPeriodType/”, {“period_type”: period_type}))
#     except Exception as e:
#         return _json({“error”: str(e)})
#
# @mcp.tool()
# async def hudud_get_timeline_by_period(period_type: str = “annual”, period: str = “”) -> str:
#     try:
#         params: dict[str, str] = {“period_type”: period_type}
#         if period:
#             params[“period”] = period
#         return _json(await _hudud_get(“/api/v1/passport/TimelineByPeriodAndPeriodType/”, params))
#     except Exception as e:
#         return _json({“error”: str(e)})


if __name__ == "__main__":
    mcp.run()
