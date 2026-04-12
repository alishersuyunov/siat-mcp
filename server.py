"""
MCP Server for siat.stat.uz — National Statistics Committee of Uzbekistan.

Catalog API:  GET https://siat.stat.uz/api/sdmx/json/
Data API:     GET https://siat.stat.uz/media/uploads/sdmx/sdmx_data_{id}.json
"""

import json
import re
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = "https://siat.stat.uz"
CATALOG_URL = f"{BASE_URL}/api/sdmx/json/"
DATA_URL = f"{BASE_URL}/media/uploads/sdmx/sdmx_data_{{id}}.json"

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "uz",
    "origin": BASE_URL,
    "referer": f"{BASE_URL}/",
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


async def _fetch_catalog() -> list[dict]:
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        r = await client.get(CATALOG_URL)
        r.raise_for_status()
        return r.json()


async def _fetch_dataset(dataset_id: int) -> dict:
    """Return the inner {metadata, data} object for a dataset."""
    url = DATA_URL.format(id=dataset_id)
    async with httpx.AsyncClient(headers=HEADERS, timeout=60) as client:
        r = await client.get(url)
        r.raise_for_status()
        raw = r.json()
    # Response is a 1-element list wrapping {metadata, data}
    if isinstance(raw, list) and raw:
        obj = raw[0]
    else:
        obj = raw
    if not isinstance(obj, dict) or "metadata" not in obj or "data" not in obj:
        raise ValueError(f"Unexpected dataset format: {str(obj)[:200]}")
    return obj


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
    return json.dumps(summary, ensure_ascii=False, indent=2)


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
        return json.dumps({"message": f"No results found for '{query}'."})
    return json.dumps(results, ensure_ascii=False, indent=2)


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
        return json.dumps({"error": f"Category {category_id} not found."})

    children = node.get("children") or []
    return json.dumps(
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
        },
        ensure_ascii=False,
        indent=2,
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
    return json.dumps(datasets, ensure_ascii=False, indent=2)


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
        return json.dumps({"error": str(e)})

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

    return json.dumps(
        {"summary": summary, "metadata": metadata, "data": data},
        ensure_ascii=False,
        indent=2,
    )


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
        return json.dumps({"error": str(e)})

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

    return json.dumps(metadata, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
