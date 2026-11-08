---
name: uzbekistan-statistics
description: Find, inspect, and retrieve public statistics of Uzbekistan from SIAT (siat.stat.uz) and NSDP (nsdp.stat.uz) using this plugin's read-only tools.
---

Use the connected statistics tools for requests about Uzbekistan's official data.

- For an ordinary indicator question, start with `siat_query`; pass the user's language, dates, and classifier when known. If it returns choices, select only a clearly justified match or ask the user.
- For discovery, use `list_categories`, `get_category`, `search_catalog`, and `list_datasets`. Do not guess dataset IDs or treat a category as a dataset.
- Before a large download, inspect `get_dataset_info` and `get_dataset_metadata` to verify the indicator, units, frequency, and classifier type.
- Use `get_dataset_table` for specific classifier IDs and periods. Use `get_dataset` for a complete single dataset, or `get_datasets` for up to 20 known IDs/codes in one request.
- Use `get_portal_counters` for portal totals, not economic observations.
- Use `nsdp_list_datasets` to discover IMF/SDMX codes and `nsdp_get_dataset` to retrieve them.

Include source URLs, units, periods, and any preliminary-data notes. Explain row or period truncation. Keep annual, quarterly, and monthly observations distinct. Preserve missing values; do not replace them with zero. NSDP `unit_mult` is a power-of-ten scale, not another observation. Report upstream errors rather than inventing data. These tools do not modify source statistics.
