# siat-mcp

![Python](https://img.shields.io/badge/python-%3E%3D3.11-blue) ![MCP](https://img.shields.io/badge/MCP-compatible-green)

MCP server for Uzbekistan official statistics — [siat.stat.uz](https://siat.stat.uz) and [nsdp.stat.uz](https://nsdp.stat.uz).

## What is this?

`siat-mcp` connects AI assistants (Claude, Cursor, etc.) to Uzbekistan's official statistical portals via the [Model Context Protocol](https://modelcontextprotocol.io). It exposes **8 tools** covering two complementary data sources:

- **siat.stat.uz** — the National Statistics Committee's SIAT portal: a rich catalog of hundreds of datasets covering population, economy, agriculture, labour, and more. Browse by category, search by keyword, and retrieve full historical tables with regional breakdowns.
- **nsdp.stat.uz** — the National Summary Data Page (IMF DSBB-compliant): 22 internationally standardized macroeconomic indicators (GDP, CPI, exchange rates, BOP, government debt, banking sector, etc.) in SDMX 2.1 XML format.

---

## Features

- **High-Performance Caching:** Implements `asyncache` and `cachetools` to cache the complete catalog schema (1-hour TTL) and recent dataset requests, avoiding redundant multi-megabyte API fetches.
- **Fast Serialization:** Uses `orjson` (C-optimized JSON parsing) to dramatically speed up the parsing and stringification of heavy statistical tables.
- **Connection Pooling:** Maintains an active HTTP keep-alive connection pool via a shared `httpx` async client to bypass repeated TLS handshake latency.

---

## Available Tools

### siat.stat.uz tools

| Tool | Description |
|------|-------------|
| `list_categories` | List top-level catalog categories with child counts |
| `get_category` | Expand a category to see its sub-categories or datasets |
| `search_catalog` | Full-tree keyword search — returns hierarchy path for each match |
| `list_datasets` | Flat list of every leaf dataset across the entire catalog |
| `get_dataset_metadata` | Preview a dataset's descriptor fields (indicator name, unit, source) without downloading data rows |
| `get_dataset` | Full dataset: summary, metadata, and year-by-region observation rows |

### nsdp.stat.uz tools

| Tool | Description |
|------|-------------|
| `nsdp_list_datasets` | List all 22 IMF/SDMX datasets with codes, names, frequencies, and XML URLs |
| `nsdp_get_dataset` | Fetch and parse an NSDP dataset by its IMF/SDMX code (e.g. `"NAG"`, `"CPI"`, `"EXR"`) |

---

### Tool details — siat.stat.uz

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

### Tool details — nsdp.stat.uz

#### `nsdp_list_datasets()`
Returns the full static catalog of 22 NSDP datasets. Each entry includes:
- `code` — IMF/SDMX identifier (e.g. `"NAG"`, `"BOP"`, `"EXR"`)
- `name` — human-readable English name
- `freq` — publication frequency (`"A"`, `"M"`, `"Q"`, or combined like `"A/Q"`)
- `xml_url` — direct URL to the SDMX 2.1 XML file
- `source` — hosting domain (`stat.uz`, `cbu.uz`, `api.mf.uz`, `uzse.uz`)

#### `nsdp_get_dataset(indicator_code)`
Fetches and parses an NSDP dataset. `indicator_code` is case-insensitive. Returns:
- **`dataset`** — name, code, prepared timestamp, reporting period, freq, xml_url, source domain
- **`series`** — list of time series, each with:
  - `indicator` — SDMX INDICATOR code (e.g. `"NGDP_PA_XDC"`)
  - `freq` — frequency code
  - `unit_mult` — scale exponent (0 = units, 6 = millions, 9 = billions)
  - `dimensions` — all SDMX dimension attributes
  - `observations` — `[{time_period, value}]` (ISO 8601 periods; `value` is `null` when missing)

**Available NSDP codes:** NAG, CPI, GGO, CGO, CGD, DCS, CBS, INR, SPI, BOP, EXD, ILV, MET, IIP, EXR, IND, LMI, PPI, FSI, POP, SDG, DOTS

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

## Typical Workflows

**Browse siat.stat.uz:**
```
1. list_categories()              → find a domain (e.g. id=5 "Population")
2. get_category(5)                → see sub-categories
3. get_category(<sub-id>)         → drill to leaf datasets
4. get_dataset_metadata(<id>)     → confirm indicator name and unit
5. get_dataset(<id>)              → retrieve full data table
```

**Search siat.stat.uz:**
```
1. search_catalog("GDP")          → find all GDP-related items
2. get_dataset_metadata(<id>)     → preview a result
3. get_dataset(<id>)              → fetch the data
```

**Use nsdp.stat.uz:**
```
1. nsdp_list_datasets()           → see all 22 IMF datasets with codes
2. nsdp_get_dataset("EXR")        → fetch monthly exchange rates (UZS/USD)
3. nsdp_get_dataset("NAG")        → fetch GDP national accounts (annual + quarterly)
```

---

## Installation

**Using `uv` (recommended):**

```bash
git clone https://github.com/alishersuyunov/siat-mcp.git
cd siat-mcp
uv pip install -e .
```

**Using `pip`:**

```bash
git clone https://github.com/alishersuyunov/siat-mcp.git
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
      "command": "path_to_python\\python.exe",
      "args": [
        "path_to_the_folder\\server.py"
      ]
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

**siat.stat.uz:**
- *"Estimate the Palma ratio over time and plot the Lorenz curve"*
- *"Which sectors have driven GDP growth in 2025?"*
- *"Show wages across sectors in 2025"*
- *"What datasets are available under the 'Labour Market' category?"*
- *"Get me the metadata for dataset 42 — what does it measure and in what units?"*

**nsdp.stat.uz:**
- *"Show me Uzbekistan's exchange rate history against the USD"*
- *"What happened to inflation (CPI) after 2017?"*
- *"Fetch Balance of Payments data and summarize the current account trend"*
- *"Get the latest GDP figures and compare annual vs quarterly growth"*
- *"What is the current level of external debt?"*

---

## Data Sources

This MCP server does not store, modify, or redistribute data — it fetches from live sources on demand.

| Source | Provider | Format |
|--------|----------|--------|
| [siat.stat.uz](https://siat.stat.uz) | National Statistics Committee of Uzbekistan | JSON |
| [nsdp.stat.uz](https://nsdp.stat.uz) | National Statistics Committee (IMF DSBB) | SDMX 2.1 XML |
| [cbu.uz](https://cbu.uz) | Central Bank of Uzbekistan | SDMX 2.1 XML |
| [api.mf.uz](https://mf.uz) | Ministry of Finance of Uzbekistan | SDMX 2.1 XML |
| [uzse.uz](https://uzse.uz) | Uzbekistan Stock Exchange | SDMX 2.1 XML |