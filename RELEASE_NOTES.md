# v0.3.0 — NSDP (nsdp.stat.uz) Integration

Added support for Uzbekistan's **National Summary Data Page** — the IMF DSBB-compliant macroeconomic data portal. This brings 22 internationally standardized datasets (GDP, CPI, BOP, exchange rates, government debt, banking sector, and more) from four hosting agencies into the same MCP interface.

**New tools:**
- **`nsdp_list_datasets`** — Lists all 22 NSDP datasets with their IMF/SDMX codes, names, frequencies, XML URLs, and source domains. No network call required.
- **`nsdp_get_dataset`** — Fetches and parses an NSDP dataset by its IMF/SDMX code (e.g. `"NAG"`, `"CPI"`, `"EXR"`). Accepts case-insensitive codes. Returns structured time-series data parsed from SDMX 2.1 XML.

**Technical notes:**
- SDMX 2.1 XML parsed with stdlib `xml.etree.ElementTree` — no new dependencies.
- A separate `httpx.AsyncClient` is used for NSDP fetches (neutral headers, no siat.stat.uz origin/referer).
- NSDP datasets are cached with a 6-hour TTL (up to 10 entries) when `cachetools`/`asyncache` are installed.
- `OBS_VALUE` is coerced to `float`; missing observations are returned as `null`.

---

# v0.2.0 — Performance & Caching Optimization

This update drastically reduces network load and JSON processing time by implementing smart caching and execution upgrades:
- **Catalog Caching:** The massive catalog JSON tree is now fetched once and dynamically cached in memory (`cachetools`+`asyncache`) with a 1-hour TTL, accelerating searches and category lookups to sub-millisecond ranges.
- **Dataset Caching:** Up to 5 consecutive datasets are now kept in an LRU memory cache temporarily, saving duplicate multi-megabyte payloads when polling for metadata prior to full table access.
- **`orjson` Implementation:** Switched base Python HTML/JSON serialization across the board to `orjson` wrapper speeds, speeding up bulk byte streaming.
- **Connection Transport Pooling:** Configured shared `httpx.AsyncClient` instances to pool Keep-Alive connections instead of repeatedly issuing SSL handshakes.

---

# v0.1.0 — Initial Release

First public release of `siat-mcp`: an MCP server that connects AI assistants to the official statistical database of the National Statistics Committee of Uzbekistan ([siat.stat.uz](https://siat.stat.uz)).

---

## What's included

**6 MCP tools:**

- **`list_categories`** — Browse top-level statistical domains (Population, Economy, Agriculture, etc.)
- **`get_category`** — Expand a category to see its sub-categories or leaf datasets
- **`search_catalog`** — Full-tree keyword search with hierarchical path context
- **`list_datasets`** — Complete flat list of every dataset in the catalog
- **`get_dataset_metadata`** — Lightweight preview of a dataset's indicator name, unit, source, and other descriptors
- **`get_dataset`** — Full dataset retrieval: summary, metadata, and year-by-region observation rows

All tools support four languages: English (`en`), Uzbek Latin (`uz`), Russian (`ru`), and Uzbek Cyrillic (`uzc`).

---

## Requirements

- Python ≥ 3.11
- [`mcp[cli]`](https://pypi.org/project/mcp/) ≥ 1.0.0
- [`httpx`](https://pypi.org/project/httpx/) ≥ 0.27.0

---

## Installation

```bash
git clone https://github.com/<your-username>/siat-mcp.git
cd siat-mcp
pip install -e .
```

Or with `uv`:

```bash
uv pip install -e .
```

---

## Claude Desktop configuration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "siat-stat-uz": {
      "command": "siat-mcp"
    }
  }
}
```

---

## Notes

- Data is fetched live from the public SIAT API — no API key required.
- Dataset IDs are stable catalog identifiers. Use `search_catalog` or `list_datasets` to discover them.
- `get_dataset_metadata` is recommended before `get_dataset` to confirm you have the right indicator.
