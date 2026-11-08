"""Check any local MCP launch command without installing it into a host app."""
import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def check(command, args):
    async with asyncio.timeout(120):
        async with stdio_client(StdioServerParameters(command=command, args=args)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {'siat_query', 'nsdp_list_datasets', 'nsdp_get_dataset'}
                result = await session.call_tool('nsdp_list_datasets', {})
                assert not result.isError
                assert 'NAG' in result.content[0].text
                print('PASS: initialize, list tools, call nsdp_list_datasets')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python scripts/smoke_stdio.py COMMAND [ARGS...]')
    asyncio.run(check(sys.argv[1], sys.argv[2:]))
