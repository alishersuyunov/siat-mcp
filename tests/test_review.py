import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
import server
from test_siat_api import resolve_immediate


class ReviewRegressionTests(unittest.TestCase):
    def test_four_digit_dataset_id_is_not_a_year(self):
        raw = {"metadata": [], "data": [{"2024": 1, "2025": 2}]}
        for request in ("2020", "dataset 2020", "dataset 2020 in 2024"):
            with self.subTest(request=request), patch.object(server, "_fetch_dataset", new_callable=AsyncMock, return_value=raw):
                result = json.loads(resolve_immediate(server.siat_query(request)))
                self.assertEqual(result["periods_returned"], ["2024" if "in 2024" in request else "2025"])

    def test_translated_summary_preserves_units(self):
        raw = {"metadata": [{"name_en": "Unit of measurement", "name_ru": "Единица", "value_ru": "тонн"}], "data": []}
        self.assertEqual(server._format_dataset(1, raw, "ru")["summary"]["unit"], "тонн")

    def test_xml_error_page_is_not_empty_success(self):
        with self.assertRaisesRegex(ValueError, "SDMX"):
            server._parse_sdmx_xml(b"<html><body>Error</body></html>")

    def test_nonfinite_observations_are_null(self):
        xml = b'<Message><DataSet><Series INDICATOR="X"><Obs TIME_PERIOD="2025" OBS_VALUE="NaN"/><Obs TIME_PERIOD="2024" OBS_VALUE="INF"/></Series></DataSet></Message>'
        values = server._parse_sdmx_xml(xml)["series"][0]["observations"]
        self.assertEqual([item["value"] for item in values], [None, None])
        with patch.object(server, "_ORJSON", False):
            self.assertNotIn("NaN", server._json(values))

    def test_invalid_input_does_not_fetch(self):
        with patch.object(server, "_fetch_dataset", new_callable=AsyncMock) as fetch:
            for kwargs in ({"period": "bad"}, {"start_year": -1}):
                self.assertEqual(json.loads(resolve_immediate(server.siat_query("1", **kwargs)))["status"], "error")
            result = json.loads(resolve_immediate(server.get_datasets(",".join(map(str, range(1, 22))))))
            self.assertIn("error", result)
            fetch.assert_not_awaited()

    def test_malformed_dataset_rejected_before_caching(self):
        response = httpx.Response(200, json={"metadata": [], "data": [None]}, request=httpx.Request("GET", "https://example.com"))
        client = AsyncMock()
        client.get.return_value = response
        with patch.object(server, "_client", return_value=client):
            fetch = getattr(server._fetch_dataset, "__wrapped__", server._fetch_dataset)
            with self.assertRaisesRegex(ValueError, "arrays of objects"):
                resolve_immediate(fetch(1))

    def test_public_host_rejects_urls_and_wildcards(self):
        for host in ("*", "https://example.com", "example.com/path"):
            with self.subTest(host=host), patch.object(server.mcp, "run") as run, patch("sys.stderr"):
                with self.assertRaises(SystemExit):
                    server.main(["--public-host", host])
                run.assert_not_called()


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_clients_closed_even_on_failure(self):
        client = AsyncMock()
        with patch.object(server, "_clients", {"test": client}):
            with self.assertRaises(RuntimeError):
                async with server._lifespan(server.mcp):
                    raise RuntimeError("test")
            client.aclose.assert_awaited_once()
            self.assertEqual(server._clients, {})
