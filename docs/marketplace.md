# Optional remote Claude and ChatGPT connections

For installation without hosting, use [local distribution](local-distribution.md).
The steps below are an optional remote-server alternative, not a requirement for
repository marketplaces or bundled desktop extensions.

The same MCP server supports local stdio clients and remote Streamable HTTP
connectors. No model API key is needed: the tools retrieve public statistics.
All tools declare read-only, non-destructive, idempotent behavior and access to
external data. This repository is not an approved marketplace listing.

## Host the remote connector

Install Python 3.11+ and run from this repository:

```sh
pip install .
siat-mcp --transport streamable-http --host 0.0.0.0 --port 8000 --public-host stats.example.com
```

Replace `stats.example.com` with your real hostname. Put a TLS reverse proxy
in front of port 8000 and route `https://stats.example.com/mcp` to the server's
`/mcp` endpoint, preserving the Host header. The server uses stateless JSON
responses. Repeat `--public-host` for additional hostnames; include the port
if your proxy forwards a nonstandard port. Keep DNS rebinding protection enabled.
The default command without arguments continues to use stdio.

This endpoint has no authentication and exposes public read-only data. Configure
hosting request limits and monitor upstream availability before public release.
If private data or user accounts are added later, implement MCP OAuth before
exposing those capabilities. Ordinary API-key headers are not a substitute for
the connector's supported authentication flow.

## Claude

For Claude Desktop local use, retain the README's stdio configuration. For remote
use, add the HTTPS `/mcp` URL through Claude's custom connector settings, choosing
no authentication. Remote connectors are configured through the UI, not through
the local `claude_desktop_config.json` file. Availability depends on account and
workspace settings.

## ChatGPT

Add the HTTPS `/mcp` endpoint as a custom MCP app/plugin in an account with
developer mode enabled; select no authentication. Test discovery of `siat_query`,
`nsdp_list_datasets`, and `nsdp_get_dataset`, then request a dataset and verify
its units, dates, and source URL. No embedded UI is required for these data tools.

## Public directory submission

Compatibility does not publish the connector. Before submitting to either
platform, provide the hosted endpoint, publisher identity, logo, support contact,
website, privacy policy and terms. Describe hosting logs and retention accurately;
the repository cannot establish an operator's privacy practices. Supply review
examples such as “List Uzbekistan's available macroeconomic indicators” and
“Find Uzbekistan GDP for 2024”, and verify them against the deployed service.
Submit through each platform's current directory process and complete review.

Official references:

- [OpenAI MCP server guide](https://developers.openai.com/plugins/build/mcp-server)
- [OpenAI submission requirements](https://developers.openai.com/plugins/deploy/submission)
- [Claude connector options](https://support.anthropic.com/en/articles/11725091-when-to-use-desktop-and-web-connectors)
