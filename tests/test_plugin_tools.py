import json
from pathlib import Path
import subprocess
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ExpandedPluginTests(unittest.TestCase):
    def test_both_source_hosts_enable_detailed_tools(self):
        for path in ('mcp.json', '.mcp.json'):
            config = json.loads((ROOT / path).read_text())
            self.assertEqual(config['mcpServers']['siat-stat-uz']['env']['SIAT_MCP_LEGACY_TOOLS'], '1')

    def test_expanded_registry_and_annotations(self):
        code = 'import asyncio,json,server; print(json.dumps([t.model_dump() for t in asyncio.run(server.mcp.list_tools())]))'
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
            env={**os.environ, 'SIAT_MCP_LEGACY_TOOLS': '1'}, capture_output=True, text=True, check=True, timeout=30)
        tools = json.loads(result.stdout)
        expected = {'siat_query', 'nsdp_list_datasets', 'nsdp_get_dataset', 'list_categories',
                    'get_category', 'search_catalog', 'list_datasets', 'get_dataset', 'get_datasets',
                    'get_dataset_info', 'get_dataset_metadata', 'get_dataset_table', 'get_portal_counters'}
        self.assertEqual({t['name'] for t in tools}, expected)
        for tool in tools:
            self.assertTrue(tool['annotations']['readOnlyHint'])
            self.assertFalse(tool['annotations']['destructiveHint'])
            self.assertTrue(tool['description'])

    def test_versions_match(self):
        import tomllib
        version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
        for path in ('plugin.json', '.claude-plugin/plugin.json'):
            self.assertEqual(json.loads((ROOT / path).read_text())['version'], version)
