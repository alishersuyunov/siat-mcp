import json
import unittest
from unittest.mock import AsyncMock, patch

import server


def resolve_immediate(coroutine):
    """Resolve mocked async calls without requiring a running event loop."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Mocked API call unexpectedly suspended")


class SiatFormattingTests(unittest.TestCase):
    def test_annual_quarterly_and_monthly_values_survive_formatting(self):
        raw = {
            "metadata": [
                {"name_en": "Indicator name", "value_en": "Exports"},
                {"name_en": "Unit of measurement", "value_en": "million USD"},
            ],
            "data": [
                {
                    "Code": "1700",
                    "Klassifikator_en": "Republic of Uzbekistan",
                    "2025": 100,
                    "2026-Q1": 30,
                    "2026-Q2": 70,
                    "2026-M01": 10,
                    "2026-M02": 20,
                    "2026-M13": 999,
                }
            ],
        }

        result = server._format_dataset(361, raw, start_year=2026)

        self.assertEqual(result["summary"]["years"], "2026-2026")
        self.assertEqual(result["summary"]["periods"], "2026-M01 to 2026-Q2")
        self.assertEqual(result["data"][0]["classifier"], "Republic of Uzbekistan")
        self.assertNotIn("2025", result["data"][0])
        self.assertEqual(result["data"][0]["2026-Q2"], 70)
        self.assertEqual(result["data"][0]["2026-M02"], 20)
        self.assertNotIn("2026-M13", result["data"][0])


class SiatApiToolTests(unittest.TestCase):
    def test_metadata_uses_dedicated_endpoint(self):
        fields = [{"key_name": "unit", "name_en": "Unit of measurement", "value_en": "Percent"}]
        with patch.object(server, "_fetch_dataset_metadata", new_callable=AsyncMock, return_value=fields) as fetch, \
             patch.object(server, "_fetch_dataset", new_callable=AsyncMock) as static_fetch:
            result = json.loads(resolve_immediate(server.get_dataset_metadata(361)))

        fetch.assert_awaited_once_with(361)
        static_fetch.assert_not_awaited()
        self.assertEqual(result, [{"key": "unit", "name": "Unit of measurement", "value": "Percent"}])

    def test_table_filters_periods_and_reports_truncation(self):
        rows = [
            {"id": 1, "name_en": "Uzbekistan", "is_root": True, "map_code": None,
             "data": [{"2025": 100}, {"2026-Q1": 30}, {"2026-Q2": 70}]},
            {"id": 2, "name_en": "Andijan", "is_root": False, "map_code": "1703",
             "data": [{"2025": 50}, {"2026-Q1": 15}]},
        ]
        with patch.object(server, "_fetch_dataset_table", new_callable=AsyncMock, return_value=rows):
            result = json.loads(resolve_immediate(server.get_dataset_table(361, periods="2026-Q1", max_rows=1)))

        self.assertEqual(result["total_rows"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["rows"][0]["values"], {"2026-Q1": 30})
        self.assertTrue(result["rows"][0]["is_root"])

    def test_r_endpoints_are_used(self):
        with patch.object(server, "_siat_api_get", new_callable=AsyncMock) as fetch:
            fetch.side_effect = [
                {"id": 361},
                {"meta_data": []},
                [],
                {"indicators": 3236},
            ]
            resolve_immediate(getattr(server._fetch_dataset_info, "__wrapped__", server._fetch_dataset_info)(361))
            resolve_immediate(getattr(server._fetch_dataset_metadata, "__wrapped__", server._fetch_dataset_metadata)(361))
            resolve_immediate(getattr(server._fetch_dataset_table, "__wrapped__", server._fetch_dataset_table)(361))
            resolve_immediate(getattr(server._fetch_portal_counters, "__wrapped__", server._fetch_portal_counters)())

        self.assertEqual(
            [call.args[0] for call in fetch.await_args_list],
            ["/sdmx/361/", "/sdmx/361/metadata/", "/sdmx/361/table/", "/common/counters/"],
        )


class SiatQueryTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            {"name_en": "Economy", "children": [
                {"id": 361, "code": "1.01.01.0001", "name_en": "Gross domestic product",
                 "period": "Annual", "children": []},
                {"id": 362, "code": "1.01.01.0002", "name_en": "Gross domestic product per capita",
                 "period": "Annual", "children": []},
            ]},
        ]
        self.dataset = {
            "metadata": [
                {"name_en": "Indicator name", "value_en": "Gross domestic product",
                 "value_ru": "Валовой внутренний продукт"},
                {"name_en": "Unit of measurement", "value_en": "billion soums",
                 "value_ru": "млрд сумов"},
                {"name_en": "Periodicity", "value_en": "Annual"},
                {"name_en": "Note", "value_en": "Preliminary", "value_ru": "Предварительные"},
            ],
            "data": [
                {"Code": "1700", "Klassifikator_en": "Uzbekistan", "Klassifikator_ru": "Узбекистан",
                 "2023": 100, "2024": 110, "2025": 120},
                {"Code": "1703", "Klassifikator_en": "Andijan", "Klassifikator_ru": "Андижан",
                 "2023": 10, "2024": 11, "2025": 12},
            ],
        }

    def test_numeric_id_fetches_without_catalog_and_binds_output(self):
        with patch.object(server, "_fetch_catalog", new_callable=AsyncMock) as catalog, \
             patch.object(server, "_fetch_dataset", new_callable=AsyncMock, return_value=self.dataset) as dataset:
            result = json.loads(resolve_immediate(server.siat_query("361", max_rows=1)))

        catalog.assert_not_awaited()
        dataset.assert_awaited_once_with(361)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["periods_returned"], ["2025"])
        self.assertEqual(result["dataset"]["unit"], "billion soums")
        self.assertEqual(len(result["rows"]), 1)
        self.assertTrue(result["classifiers_truncated"])

    def test_exact_name_resolves_in_one_call(self):
        with patch.object(server, "_fetch_catalog", new_callable=AsyncMock, return_value=self.catalog), \
             patch.object(server, "_fetch_dataset", new_callable=AsyncMock, return_value=self.dataset) as dataset:
            result = json.loads(resolve_immediate(server.siat_query("Gross domestic product")))

        dataset.assert_awaited_once_with(361)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["dataset"]["code"], "1.01.01.0001")

    def test_common_gdp_request_with_year_resolves_in_one_call(self):
        with patch.object(server, "_fetch_catalog", new_callable=AsyncMock, return_value=self.catalog), \
             patch.object(server, "_fetch_dataset", new_callable=AsyncMock, return_value=self.dataset) as dataset:
            result = json.loads(resolve_immediate(server.siat_query("Show me GDP in 2024")))

        dataset.assert_awaited_once_with(361)
        self.assertEqual(result["periods_returned"], ["2024"])

    def test_exact_catalog_code_resolves_in_one_call(self):
        with patch.object(server, "_fetch_catalog", new_callable=AsyncMock, return_value=self.catalog), \
             patch.object(server, "_fetch_dataset", new_callable=AsyncMock, return_value=self.dataset) as dataset:
            result = json.loads(resolve_immediate(server.siat_query("1.01.01.0001")))

        dataset.assert_awaited_once_with(361)
        self.assertEqual(result["status"], "ok")

    def test_trend_request_infers_period_range_and_bounds_it(self):
        with patch.object(server, "_fetch_catalog", new_callable=AsyncMock, return_value=self.catalog), \
             patch.object(server, "_fetch_dataset", new_callable=AsyncMock, return_value=self.dataset):
            result = json.loads(resolve_immediate(server.siat_query("GDP trend since 2023", max_periods=2)))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["periods_returned"], ["2024", "2025"])
        self.assertTrue(result["periods_truncated"])

    def test_ambiguous_query_returns_choices_without_fetching_tables(self):
        with patch.object(server, "_fetch_catalog", new_callable=AsyncMock, return_value=self.catalog), \
             patch.object(server, "_fetch_dataset", new_callable=AsyncMock) as dataset:
            result = json.loads(resolve_immediate(server.siat_query("gross domestic")))

        dataset.assert_not_awaited()
        self.assertEqual(result["status"], "choose_dataset")
        self.assertEqual([item["id"] for item in result["matches"]], [361, 362])

    def test_requested_year_classifier_and_language(self):
        with patch.object(server, "_fetch_catalog", new_callable=AsyncMock) as catalog, \
             patch.object(server, "_fetch_dataset", new_callable=AsyncMock, return_value=self.dataset):
            result = json.loads(resolve_immediate(server.siat_query("dataset 361 in 2024", classifier="1703", lang="ru")))

        catalog.assert_not_awaited()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["periods_returned"], ["2024"])
        self.assertEqual(result["rows"], [{"code": "1703", "classifier": "Андижан", "values": {"2024": 11}}])

    def test_russian_metadata_and_explicit_period(self):
        with patch.object(server, "_fetch_catalog", new_callable=AsyncMock) as catalog, \
             patch.object(server, "_fetch_dataset", new_callable=AsyncMock, return_value=self.dataset):
            result = json.loads(resolve_immediate(server.siat_query("361", classifier="1703", period="2024", lang="ru")))

        catalog.assert_not_awaited()
        self.assertEqual(result["dataset"]["name"], "Валовой внутренний продукт")
        self.assertEqual(result["dataset"]["unit"], "млрд сумов")
        self.assertEqual(result["dataset"]["notes"], ["Предварительные"])
        self.assertEqual(result["rows"], [{"code": "1703", "classifier": "Андижан", "values": {"2024": 11}}])

    def test_default_registry_has_one_siat_tool(self):
        names = {tool.name for tool in resolve_immediate(server.mcp.list_tools())}
        self.assertEqual(names, {"siat_query", "nsdp_list_datasets", "nsdp_get_dataset"})


if __name__ == "__main__":
    unittest.main()
