from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import httpx
import server


class CompatibilityTests(unittest.TestCase):
    def test_default_remains_stdio(self):
        with patch.object(server.mcp, "run") as run:
            server.main([])
        run.assert_called_once_with(transport="stdio")

    def test_remote_configuration(self):
        with patch.object(server.mcp, "run") as run:
            server.main(["--transport", "streamable-http", "--public-host", "stats.example.com"])
        run.assert_called_once_with(transport="streamable-http")
        self.assertIn("stats.example.com", server.mcp.settings.transport_security.allowed_hosts)
        self.assertTrue(server.mcp.settings.transport_security.enable_dns_rebinding_protection)

    def test_http_initialize_list_and_call(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable, str(Path(server.__file__).resolve()), "--transport",
            "streamable-http", "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False) as client:
                for attempt in range(100):
                    try:
                        client.get("/mcp")
                        break
                    except httpx.ConnectError:
                        if process.poll() is not None:
                            self.fail("Server exited before startup")
                        time.sleep(0.1)
                else:
                    self.fail("Server did not become ready within 10 seconds")
                def rpc(method, params):
                    response = client.post("/mcp", headers={
                        "Accept": "application/json, text/event-stream"}, json={
                        "jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                    self.assertEqual(response.status_code, 200, response.text)
                    body = response.json()
                    self.assertNotIn("error", body)
                    return body["result"]
                result = rpc("initialize", {"protocolVersion": "2025-03-26",
                    "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
                self.assertIn("tools", result["capabilities"])
                result = rpc("tools/list", {})
                self.assertEqual(len(result["tools"]), 3)
                for tool in result["tools"]:
                    self.assertTrue(tool["annotations"]["readOnlyHint"])
                    self.assertFalse(tool["annotations"]["destructiveHint"])
                result = rpc("tools/call", {"name": "nsdp_list_datasets", "arguments": {}})
                self.assertFalse(result.get("isError", False))
                self.assertIn("NAG", result["content"][0]["text"])
        finally:
            process.terminate()
            process.wait(timeout=10)
