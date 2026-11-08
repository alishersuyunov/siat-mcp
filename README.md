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

- **Claude and ChatGPT compatibility:** Local stdio and remote Streamable HTTP at `/mcp`, with read-only tool annotations. See [connection and marketplace setup](docs/marketplace.md) for hosting, connection steps, and public directory submission requirements.
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

## Install from a marketplace or desktop package

No separately hosted MCP server is needed. The tools run on the user's computer
and fetch public statistics directly.

**Release status:** These installation files are prepared locally. Repository
marketplace commands will work for other users after the changes are pushed to
GitHub. Desktop downloads must first be attached to a GitHub release. There is
no approved public directory listing yet.

| Where you use it | Installation route | Runtime requirement |
|------------------|--------------------|---------------------|
| Claude Code | Add this GitHub marketplace, then install `siat-mcp` | `uv` installed once; it manages Python and dependencies |
| Codex / supported local ChatGPT Work | Add the repository marketplace, then install `siat-mcp` | `uv` installed once; run the chat locally |
| Claude Desktop | Open the `.mcpb` file for your operating system and click Install | Native package includes Python and dependencies |
| ChatGPT Desktop public directory | Install an approved desktop plugin | Publication needs OpenAI partner approval and review |

### Claude Code

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) once if it is
not already available, then restart Claude Code so it can find it. In Claude Code:

```text
/plugin marketplace add alishersuyunov/siat-mcp
/plugin install siat-mcp@siat-statistics
```

Where your client has **Add marketplace**, use
`https://github.com/alishersuyunov/siat-mcp`, then select **siat-mcp → Install**.
The first tool start needs internet access to download its runtime/dependencies.
You do not need to edit Claude's JSON configuration.

### Codex

With `uv` available, register and install from a terminal:

```text
codex plugin marketplace add alishersuyunov/siat-mcp
codex plugin add siat-mcp@siat-statistics
```

Or use your client's marketplace picker when available. Start a new local chat
after installation. A cloud chat cannot launch this local process.

### Claude Desktop: no Python installation

Obtain the `.mcpb` release asset matching your operating system and processor.
Open it with Claude Desktop and confirm **Install**. Ask it to list NSDP datasets.
The Windows AMD64 package is built locally; other operating systems need native
builds before corresponding download links can be published. A `.mcpb` file is
for Claude Desktop, not ChatGPT.

### ChatGPT Desktop

The native `desktop-plugin.zip` is the separate OpenAI package. It includes the
same local executable and can be used in supported local plugin workflows.
It is **not** a universally installable web app or an approved public listing.
OpenAI currently restricts public local-MCP submissions to approved partners.
See [local packaging and release instructions](docs/local-distribution.md).

Prefer manual setup or want to develop the server? Continue below.

## Installation: start here

**New to MCP?** It is the connection that lets an AI assistant use this project's statistics tools. You do not need to write any code. You will download the project, install its dependencies, and tell your assistant where to find it.

The guide below sets up **Claude Desktop on your own computer**. You do not need an API key or a hosting account for this setup. Keep the downloaded project folder: Claude will use it whenever it starts the tools.

> **Using ChatGPT or Claude in a web browser?** Those need a publicly accessible HTTPS server. Installing the project on your laptop alone does not connect it to the web app. See the separate [remote connection guide](docs/marketplace.md). This project does not currently provide a shared hosted endpoint.

### 1. Install Python and Claude Desktop

- Install **Python 3.11 or newer** from [python.org](https://www.python.org/downloads/). On Windows, enable **Add python.exe to PATH** if the installer offers it.
- Install **Claude Desktop** from [Claude's download page](https://claude.ai/download).

On Windows, open **PowerShell** from the Start menu and run:

```powershell
py --version
```

On macOS, open **Terminal** and run:

```bash
python3 --version
```

You should see `Python 3.11` or a newer version. If the command is not found, close and reopen the terminal after installing Python.

### 2. Download this project

1. Open the [siat-mcp GitHub page](https://github.com/alishersuyunov/siat-mcp).
2. Click the green **Code** button, then **Download ZIP**.
3. Extract the ZIP into a folder you plan to keep, such as your Documents folder. On Windows, right-click the ZIP and choose **Extract All**.
4. Open the extracted folder containing **`server.py`** and **`pyproject.toml`**. The folder will usually be called `siat-mcp-main`.

You do not need Git for this method.

### 3. Install the project's dependencies

Open a terminal in that extracted folder. On Windows, open the folder in File Explorer, click the address bar, type `powershell`, and press Enter. On macOS, type `cd ` in Terminal, drag the extracted folder into the window, then press Enter.

Copy and run the following commands **one line at a time**. Do not copy the surrounding code-box markers.

**Windows — PowerShell:**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe server.py --help
```

**macOS — Terminal:**

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install .
./.venv/bin/python server.py --help
```

The first command creates a `.venv` folder for this project's Python dependencies. The second installs them and needs an internet connection. The final command should show help text containing `--transport`, `--host`, and `--port`.

**If you see that help text, installation worked.** You do not need to activate the environment or leave the terminal running.

### 4. Connect it to Claude Desktop

Claude needs two full paths: the Python program inside `.venv`, and this project's `server.py` file.

Print the exact paths for your computer:

**Windows — in the same PowerShell window:**

```powershell
(Resolve-Path .\.venv\Scripts\python.exe).Path
(Resolve-Path .\server.py).Path
```

**macOS — in the same Terminal window:**

```bash
printf '%s\n' "$PWD/.venv/bin/python" "$PWD/server.py"
```

Next, open Claude's configuration file in a plain-text editor such as Notepad on Windows or TextEdit in plain-text mode on macOS:

| System | Configuration file |
|--------|--------------------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

On Windows, press **Win + R**, paste `%APPDATA%\Claude`, and press Enter to open the folder. On macOS, use Finder's **Go → Go to Folder** and enter `~/Library/Application Support/Claude`.

If the file does not exist, create it with the exact name `claude_desktop_config.json`. On Windows, make sure it is not accidentally saved as `claude_desktop_config.json.txt`.

For a new or empty configuration file, paste this example and **replace both example paths with your own**:

**Windows example:**

```json
{
  "mcpServers": {
    "siat-stat-uz": {
      "command": "C:/Users/YourName/Documents/siat-mcp-main/.venv/Scripts/python.exe",
      "args": ["C:/Users/YourName/Documents/siat-mcp-main/server.py"]
    }
  }
}
```

Use forward slashes (`/`) in the Windows JSON paths, as shown above. If you paste paths from PowerShell, change each backslash (`\`) to `/`. Keep the quotation marks, even if your path contains spaces.

**macOS example:**

```json
{
  "mcpServers": {
    "siat-stat-uz": {
      "command": "/Users/YourName/Documents/siat-mcp-main/.venv/bin/python",
      "args": ["/Users/YourName/Documents/siat-mcp-main/server.py"]
    }
  }
}
```

> **Already have other MCP tools configured?** Keep them. Add only the `siat-stat-uz` entry inside your existing `mcpServers` object, with a comma between entries. Do not replace your entire configuration or add a second `mcpServers` key.

Save the file, then **fully quit and reopen Claude Desktop**. On Windows, quit it from the system tray if it remains running there; on macOS, use **Cmd + Q**. Claude starts the server automatically.

### 5. Try your first request

Start a new Claude conversation and ask:

> Use siat-stat-uz to list the available NSDP datasets.

If Claude asks for permission to use the tool, approve the request. You should receive a list containing codes such as **NAG** (GDP), **CPI** (consumer prices), and **EXR** (exchange rates). This first check uses a built-in list and does not download statistics.

Then try a request that retrieves live data:

> Use siat-stat-uz to fetch the EXR exchange-rate dataset and include its source link.

### Troubleshooting

| What you see | What to try |
|--------------|-------------|
| `py` or `python3` is not found | Install Python, reopen your terminal, and check its version again. On Windows, try `python --version`; if that works, use `python` instead of `py` in step 3. |
| Python is older than 3.11 | Install a supported version before creating `.venv`. On macOS, use the installed version's command, such as `python3.13`, if `python3` still points to the older version. |
| “Directory is not installable” or `server.py` cannot be found | Open the folder containing both `server.py` and `pyproject.toml`. You may still be in the outer ZIP extraction folder. |
| The dependency installation fails | Check your internet connection and read the last lines of the error. Keep that error text when asking for help. |
| Claude cannot start the server | Check both full paths in the configuration. The `command` must point to Python **inside `.venv`**, and the project folder must still exist. |
| Claude reports an invalid configuration | Check commas, double quotation marks, and braces. On Windows, use `/` in paths and check that the file does not end in `.txt`. |
| The tools do not appear | Save the configuration and fully quit and reopen Claude. Managed work accounts may restrict local MCP tools. |
| The dataset list works, but live data fails | The upstream statistics website may be unavailable. Try again later and include the returned error when reporting the problem. |
| Running `server.py` appears to do nothing | Without `--help`, the server waits for an MCP client. That is expected. Press **Ctrl + C** to stop it; Claude normally launches it for you. |

Need help? [Open a GitHub issue](https://github.com/alishersuyunov/siat-mcp/issues) with your operating system, the step that failed, and the error message. Remove any private information from configuration files before sharing them.

### Other installation options

**Already use Git and uv?**

```bash
git clone https://github.com/alishersuyunov/siat-mcp.git
cd siat-mcp
uv venv
uv pip install -e .
```

Then follow steps 4–5 above, using the paths inside your cloned folder.

**Using Claude Code?** After completing step 3, register the server using your actual full paths:

```bash
claude mcp add siat-stat-uz -- "/absolute/path/to/.venv/bin/python" "/absolute/path/to/server.py"
```

On Windows, use the full path to `.venv/Scripts/python.exe` for the first path. Keep quotation marks around paths containing spaces.

**Need the detailed SIAT tools?** The default setup exposes three tools. Advanced users can set `SIAT_MCP_LEGACY_TOOLS=1` in the server's environment to expose the additional tools listed earlier in this README.

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

This MCP server fetches public data on demand, caches responses in memory, and returns them to the connected client. SIAT cache entries expire after one hour; NSDP XML entries expire after six hours. It does not modify the upstream sources.

| Source | Provider | Format |
|--------|----------|--------|
| [siat.stat.uz](https://siat.stat.uz) | National Statistics Committee of Uzbekistan | JSON |
| [api.siat.stat.uz](https://api.siat.stat.uz) | National Statistics Committee of Uzbekistan | JSON detail, metadata, and table APIs |
| [nsdp.stat.uz](https://nsdp.stat.uz) | National Statistics Committee (IMF DSBB) | SDMX 2.1 XML |
| [cbu.uz](https://cbu.uz) | Central Bank of Uzbekistan | SDMX 2.1 XML |
| [api.mf.uz](https://mf.uz) | Ministry of Economy and Finance of Uzbekistan | SDMX 2.1 XML |
| [uzse.uz](https://uzse.uz) | Uzbekistan Stock Exchange | SDMX 2.1 XML |

## Development checks

Run `python -m unittest discover -s tests -v` after installing the project.
The compatibility test starts a temporary local HTTP server; it needs loopback network access.
Build distribution archives with `uv build`. Bulk retrieval accepts at most 20 dataset IDs/codes per call.
