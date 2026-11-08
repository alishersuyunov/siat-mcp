# Local distribution and release status

This project runs locally. No publisher-hosted MCP service is needed. Repository
marketplaces and public platform directories are different distribution channels.

## What is included

- `.claude-plugin/marketplace.json`: GitHub marketplace catalog, also supported by
  Codex as a compatibility format. Its `policy` field is for Codex; Claude ignores it.
- `.claude-plugin/plugin.json` and `.mcp.json`: Claude Code plugin and local launch.
- `plugin.json` and `mcp.json`: portable OpenAI plugin and local launch.
- `scripts/build_plugins.py`: explicit-file packaging; excludes local settings,
  caches, tests, marketplace catalogs, and unrelated repository files from plugin ZIPs.
- Native `.mcpb`: Claude Desktop bundle with Python and dependencies included.
- Native `desktop-plugin.zip`: OpenAI local plugin with the same bundled executable.

Source marketplace installs require `uv` on PATH. They use `uv tool run --from`
to install the selected package into uv's cache, rather than writing a virtual
environment inside the plugin cache. No global pip install is performed. The
source path comes from the host, so paths containing spaces remain one argument.
Native desktop packages do not need uv or Python installed by the end user.

## Build

Run from the repository root. Build on the target OS/architecture; PyInstaller
is not a cross compiler. The current Windows AMD64 build is unsigned.

```text
uv run --no-project --with . --with pyinstaller python -m PyInstaller --noconfirm --onedir --name siat-mcp --distpath build/native --workpath build/pyinstaller --specpath build --collect-all mcp server.py
python scripts/build_plugins.py --native build/native/siat-mcp
```

Outputs are in `dist/`. Run `python scripts/build_plugins.py` to create only the
source plugin ZIP. Packages use the version in `plugin.json`; keep that version,
`.claude-plugin/plugin.json`, and `pyproject.toml` synchronized before release.
The native packaging script rejects symlinks rather than silently breaking them;
platforms producing symlinks need packaging support before release.

## Verify and distribute

1. Run the tests and validate the source plugin with `claude plugin validate .`.
2. Run `python scripts/smoke_stdio.py build/native/siat-mcp/siat-mcp.exe` on Windows
   (omit `.exe` on other operating systems).
3. Build and inspect archives, then test an actual clean installation in each
   target app. A protocol smoke test alone does not verify the host installer.
4. For GitHub marketplace installs, commit and push the source/manifests.
5. Attach native assets to a GitHub release; add actual release download links to
   the README after the upload. Do not advertise macOS/Linux assets until built
   and tested there. Do not bypass OS security warnings for unsigned binaries.

Nothing in these scripts pushes, uploads, submits, or publishes automatically.

## Public directory preparation is separate

Claude desktop directory listing requires its submission/review process.
OpenAI public local MCP submissions currently require partner allowlisting;
this cannot be enabled through a repository manifest. The OpenAI ZIP is a local
package, **not submission-ready**. Before a public submission, confirm publisher
identity, countries, commerce declarations, published privacy and terms URLs,
icon, clean-install evidence, and a reviewer-accessible recorded demo. The existing
repository demo has not been verified as a demonstration of these new packages.
No policy attestations or approval status have been invented in the manifests.

Suggested demo: install the package; list NSDP indicators; retrieve EXR; show its
source link. Then query SIAT GDP for 2024, retaining units and source. Show an
unknown NSDP code returning an error rather than invented statistics.

References:

- [Claude marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude desktop bundles](https://www.anthropic.com/research/desktop-extensions)
- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [OpenAI local submission eligibility](https://developers.openai.com/plugins/deploy/desktop-only)

## Expanded tools (0.3.1)

All plugin launch configurations enable `SIAT_MCP_LEGACY_TOOLS=1`. This exposes
13 read-only tools through one connector, including catalog browsing, metadata,
filtered tables, bulk retrieval (up to 20 datasets), and NSDP. Standalone launches
retain three tools unless that environment variable is set. Update/reinstall the
plugin and start a new chat to refresh cached tool discovery.
