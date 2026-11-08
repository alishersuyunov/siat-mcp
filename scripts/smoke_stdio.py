"""Check any local MCP launch command without installing it into a host app."""
import asyncio
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def check(command, args):
    async with asyncio.timeout(120):
        async with stdio_client(StdioServerParameters(command=command, args=args, env={'SIAT_MCP_LEGACY_TOOLS': os.environ.get('SIAT_MCP_LEGACY_TOOLS', '0')})) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                expected = {'siat_query', 'nsdp_list_datasets', 'nsdp_get_dataset'}
                if os.environ.get('SIAT_MCP_LEGACY_TOOLS') == '1':
                    expected |= {'list_categories', 'get_category', 'search_catalog', 'list_datasets',
                                 'get_dataset', 'get_datasets', 'get_dataset_info', 'get_dataset_metadata',
                                 'get_dataset_table', 'get_portal_counters'}
                assert {t.name for t in tools.tools} == expected
                assert all(t.annotations.readOnlyHint for t in tools.tools)
                result = await session.call_tool('nsdp_list_datasets', {})
                assert not result.isError
                assert 'NAG' in result.content[0].text
                print(f'PASS: initialize, {len(tools.tools)} read-only tools, call nsdp_list_datasets')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python scripts/smoke_stdio.py COMMAND [ARGS...]')
    asyncio.run(check(sys.argv[1], sys.argv[2:]))
