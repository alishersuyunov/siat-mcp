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
