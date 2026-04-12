# siat-mcp

![Python](https://img.shields.io/badge/python-%3E%3D3.11-blue) ![MCP](https://img.shields.io/badge/MCP-compatible-green)

MCP server for [siat.stat.uz](https://siat.stat.uz) — the official statistical database of the National Statistics Committee of Uzbekistan.

## What is this?

`siat-mcp` connects AI assistants (Claude, Cursor, etc.) to Uzbekistan's official national statistics portal via the [Model Context Protocol](https://modelcontextprotocol.io). It exposes 6 tools that let you browse the catalog, search for indicators, and retrieve full historical datasets — population figures, GDP components, trade statistics, social indicators, and more — directly in your AI workflow.

Data is served by the National Statistics Committee of Uzbekistan ([stat.uz](https://stat.uz)) and accessed through the public SIAT (Statistical Information and Analysis Tool) API.

---

## Available Tools

| Tool | Description |
|------|-------------|
| `list_categories` | List top-level catalog categories with child counts |
| `get_category` | Expand a category to see its sub-categories or datasets |
| `search_catalog` | Full-tree keyword search — returns hierarchy path for each match |
| `list_datasets` | Flat list of every leaf dataset across the entire catalog |
| `get_dataset_metadata` | Preview a dataset's descriptor fields (indicator name, unit, source) without downloading data rows |
| `get_dataset` | Full dataset: summary, metadata, and year-by-region observation rows |

### Tool details

#### `list_categories(lang?)`
Returns the top-level statistical domains (e.g. "Population", "Economy", "Agriculture") with a count of how many sub-items each contains.

#### `get_category(category_id, lang?)`
Returns the immediate children of a category — either sub-categories (drill deeper) or leaf datasets (ready to fetch).

#### `search_catalog(query, lang?)`
Case-insensitive substring search through the full catalog tree. Each result includes a `path` field showing where in the hierarchy it lives (e.g. `"Economy > National Accounts > GDP"`). Results with `has_children: false` are leaf datasets you can pass directly to `get_dataset`.

#### `list_datasets(lang?)`
Returns every leaf dataset in the catalog as a flat list. Includes `id`, multilingual names, `code`, `period`, `updated_at`, and `status`. Use this for bulk inspection or filtering.

#### `get_dataset_metadata(dataset_id, lang?)`
Lightweight call — fetches only the metadata fields (indicator name, unit of measurement, periodicity, data source, etc.) without downloading the full data table. Useful for confirming a dataset is what you want before fetching it.

#### `get_dataset(dataset_id, lang?)`
Fetches the complete dataset. Returns three sections:
- **`summary`** — indicator name, unit, year range, and number of regions
- **`metadata`** — all descriptor fields
- **`data`** — list of observation rows: `code`, `region`, and year-keyed values (`"2020": 1234.5`, `"2021": 1289.0`, ...)

---

## Language Support

All tools accept an optional `lang` parameter:

| Code | Language |
|------|---------|
| `en` | English (default) |
| `uz` | Uzbek — Latin script |
| `ru` | Russian |
| `uzc` | Uzbek — Cyrillic script |

If a name is unavailable in the requested language, the server falls back to English, then Uzbek.

---

## Typical Workflow

```
1. list_categories()              → find a domain of interest (e.g. id=5 "Population")
2. get_category(5)                → see sub-categories inside "Population"
3. get_category(<sub-id>)         → drill down to leaf datasets
4. get_dataset_metadata(<id>)     → confirm the indicator name and unit
5. get_dataset(<id>)              → retrieve the full data table
```

Or search directly:

```
1. search_catalog("GDP")          → find all GDP-related datasets and categories
2. get_dataset_metadata(<id>)     → preview a promising result
3. get_dataset(<id>)              → fetch the data
```

---

## Installation

**Using `uv` (recommended):**

```bash
git clone https://github.com/<your-username>/siat-mcp.git
cd siat-mcp
uv pip install -e .
```

**Using `pip`:**

```bash
git clone https://github.com/<your-username>/siat-mcp.git
cd siat-mcp
pip install -e .
```

Python 3.11 or newer is required.

---

## Configuration

### Claude Desktop

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "siat-stat-uz": {
      "command": "siat-mcp"
    }
  }
}
```

File locations:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

### Claude Code (CLI)

```bash
claude mcp add siat-stat-uz -- siat-mcp
```

---

## Example Prompts

Once configured, you can ask your AI assistant things like:

- *"What statistical categories are available on siat.stat.uz?"*
- *"Search the Uzbekistan statistics catalog for datasets about inflation."*
- *"Show me population data for Uzbekistan's regions from 2015 to 2023."*
- *"What datasets are available under the 'Labour Market' category? Show me the unemployment rate data."*
- *"Get me the metadata for dataset 42 — what does it measure and in what units?"*

---

## Data Source

All data is served by the **National Statistics Committee of the Republic of Uzbekistan** via the public SIAT API at [siat.stat.uz](https://siat.stat.uz). This MCP server does not store, modify, or redistribute data — it fetches from the live API on demand.
