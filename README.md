# siat-mcp

![Python](https://img.shields.io/badge/python-%3E%3D3.11-blue) ![MCP](https://img.shields.io/badge/MCP-compatible-green)

## Demo

[![Watch the demo](https://img.shields.io/badge/▶_Watch_Demo-blue?style=for-the-badge)](Demo%20-%20siat-MCP.mp4)

---

MCP server for Uzbekistan official statistics — [siat.stat.uz](https://siat.stat.uz) and [nsdp.stat.uz](https://nsdp.stat.uz).

## What is this?

`siat-mcp` connects AI assistants (Claude, Cursor, etc.) to Uzbekistan's official statistical portals via the [Model Context Protocol](https://modelcontextprotocol.io). Its default interface exposes **three tools**, including one SIAT tool that searches and retrieves data in a single request:

- **siat.stat.uz** — National Statistics Committee's SIAT portal: hundreds of datasets covering population, economy, agriculture, labour, and more. Browse by category, search by keyword, and retrieve full historical tables with regional breakdowns.
- **nsdp.stat.uz** — National Summary Data Page (IMF DSBB-compliant): 22 internationally standardized macroeconomic indicators (GDP, CPI, exchange rates, BOP, government debt, banking sector, etc.) in SDMX 2.1 XML format.

---

## Features

- **High-Performance Caching:** Implements `asyncache` and `cachetools` to cache the catalog, dataset files, and API responses for one hour, avoiding redundant multi-megabyte fetches while allowing updates to appear.
- **Fast JSON Handling:** Uses `pysimdjson` for SIMD-accelerated inbound JSON parsing when available, with `orjson` kept for fast output serialization and as a parser fallback.
- **Connection Pooling:** Maintains an active HTTP keep-alive connection pool via a shared `httpx` async client to bypass repeated TLS handshake latency.

---

## Available Tools

### siat.stat.uz tools

| Tool | Description |
|------|-------------|
| `siat_query` | Find an indicator by name, code, or ID and return a bounded table with metadata in one call |

### nsdp.stat.uz tools

| Tool | Description |
|------|-------------|
| `nsdp_list_datasets` | List all 22 IMF/SDMX datasets with codes, names, frequencies, and XML URLs |
| `nsdp_get_dataset` | Fetch and parse an NSDP dataset by its IMF/SDMX code (e.g. `"NAG"`, `"CPI"`, `"EXR"`) |

### Detailed SIAT tools (opt in)

Set `SIAT_MCP_LEGACY_TOOLS=1` in the MCP server's environment to expose these tools alongside the default three. They support catalog inspection, raw tables, bulk downloads, and compatibility with existing clients.

| Tool | Description |
|------|-------------|
| `list_categories` | List top-level catalog categories with child counts |
| `get_category` | Expand a category to see its sub-categories or datasets |
| `search_catalog` | Full-tree keyword search — returns hierarchy path for each match |
| `list_datasets` | Flat list of every leaf dataset across the entire catalog |
| `get_dataset_metadata` | Preview a dataset's descriptor fields (indicator name, unit, source) without downloading data rows |
| `get_dataset_info` | Get a dataset's code, frequency, classifier type, update timestamp, and source links |
| `get_dataset_table` | Query the table API for bounded classifier rows and selected periods |
| `get_portal_counters` | Get live SIAT totals for indicators, SDMX items, and downloads |
| `get_dataset` | Full dataset: summary, metadata, and annual/quarterly/monthly observation rows |
| `get_datasets` | Bulk dataset retrieval by comma-separated ids or catalog codes, with compact defaults for multi-series analysis |

<!-- hudud.stat.uz tools are currently disabled -->

---

### SIAT quick use

Call `siat_query` directly; catalog browsing is unnecessary for a normal data request:

```text
siat_query(request="Gross domestic product")
siat_query(request="dataset 361 in 2024", classifier="1703", lang="ru")
siat_query(request="1.01.01.0001", period="all", start_year=2020)
```

`request` accepts a natural-language indicator description, exact catalog code, or numeric dataset ID. By default the response returns the latest period and at most 15 classifier rows. A year in the request selects that year; phrases such as "trend" or "since 2020" select a bounded time series. Use `classifier` for a territory, sector, or classifier code. Use `period="all"`, `start_year`, `end_year`, `max_rows`, and `max_periods` for explicit control. If the name matches several indicators, the tool returns up to five named choices with IDs; call it once more with the selected ID. The response reports when rows or periods were truncated and links to the source file.

### Detailed SIAT tool reference (opt in)

#### `list_categories(lang?)`
Returns the top-level statistical domains (e.g. "Population", "Economy", "Agriculture") with a count of how many sub-items each contains.

#### `get_category(category_id, lang?)`
Returns the immediate children of a category — either sub-categories (drill deeper) or leaf datasets (ready to fetch).
When a category contains multiple leaf datasets, the response includes a `bulk_fetch` hint with comma-separated ids for `get_datasets`.

#### `search_catalog(query, lang?)`
Case-insensitive substring search through the full catalog tree. Each result includes a `path` field showing where in the hierarchy it lives (e.g. `"Economy > National Accounts > GDP"`). Results with `has_children: false` are leaf datasets you can pass directly to `get_dataset`.

#### `list_datasets(lang?)`
Returns every leaf dataset in the catalog as a flat list. Includes `id`, multilingual names, `code`, `period`, `updated_at`, and `status`. Use this for bulk inspection or filtering.

#### `get_dataset_metadata(dataset_id, lang?)`
Uses SIAT's dedicated `/sdmx/{id}/metadata/` endpoint to fetch descriptor fields without downloading the full data table. Fields include a stable `key` when the API provides one.
The dedicated endpoint can contain fewer publication fields than the metadata embedded in the downloadable JSON; use `get_dataset` when those additional fields are needed.

#### `get_dataset_info(dataset_id, lang?)`
Uses `/sdmx/{id}/` to identify the dataset's classifier type (for example, territories), catalog code, frequency, status, and update timestamp without downloading observations.

#### `get_dataset_table(dataset_id, lang?, classifier_ids?, periods?, start_year?, end_year?, max_rows?)`
Uses `/sdmx/{id}/table/` to return classifier IDs, labels, root flags, map codes, and period values. Responses are limited to 10 classifier rows by default (maximum 100) and report when additional rows were omitted. `periods` accepts exact comma-separated labels such as `2025,2026-Q1`.

#### `get_portal_counters()`
Uses `/common/counters/` for current portal totals. These counts describe SIAT coverage and activity, not an indicator's statistical observations.

#### `get_dataset(dataset_id, lang?)`
Fetches the complete dataset. Returns three sections:
- **`summary`** — indicator name, unit, year and period ranges, and row count
- **`metadata`** — all descriptor fields
- **`data`** — list of observation rows: `code`, `classifier` label (also in the legacy `region` field), and annual, quarterly, or monthly values (`"2024": 1234.5`, `"2025-Q1": 300.2`, `"2025-M01": 100.1`, ...)

#### `get_datasets(dataset_ids?, dataset_codes?, lang?, include_metadata?, start_year?, end_year?)`
Fetches multiple SIAT datasets in one MCP tool call. Pass comma-separated dataset ids such as `"544,548,582"` or leaf catalog codes such as `"1.01.01.0001,1.01.01.0002"`. By default, metadata is omitted to reduce token usage in bulk calls; set `include_metadata=true` when descriptor fields are needed. Use `start_year` and `end_year` to trim annual, quarterly, and monthly observation columns.

Example: `get_datasets(dataset_ids="3093,3094,3095,3096,3097,624", include_metadata=false)`.

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

SIAT tools that return names accept an optional `lang` parameter:

| Code | Language |
|------|---------|
| `en` | English (default) |
| `uz` | Uzbek — Latin script |
| `ru` | Russian |
| `uzc` | Uzbek — Cyrillic script |

If a name is unavailable in the requested language, the server falls back to English, then Uzbek.

---

## Typical Workflows

**Get a SIAT indicator:**
```
siat_query(request="Gross domestic product")
```

**Get a SIAT trend for one classifier:**
```
siat_query(request="361", classifier="Uzbekistan", period="all", start_year=2015)
```

If the indicator description is ambiguous, use an ID from the returned `matches` list in a second `siat_query` call.

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

To expose the detailed SIAT tools for an existing client, set `SIAT_MCP_LEGACY_TOOLS=1` in that MCP server's environment and restart the server. The default tool list stays small so an assistant can select `siat_query` without first navigating several catalog tools.

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
| [api.siat.stat.uz](https://api.siat.stat.uz) | National Statistics Committee of Uzbekistan | JSON detail, metadata, and table APIs |
| [nsdp.stat.uz](https://nsdp.stat.uz) | National Statistics Committee (IMF DSBB) | SDMX 2.1 XML |
| [cbu.uz](https://cbu.uz) | Central Bank of Uzbekistan | SDMX 2.1 XML |
| [api.mf.uz](https://mf.uz) | Ministry of Economy and Finance of Uzbekistan | SDMX 2.1 XML |
| [uzse.uz](https://uzse.uz) | Uzbekistan Stock Exchange | SDMX 2.1 XML |
