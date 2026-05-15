"""Extract structured data context from the agent's tool trace.

Handles all three data tool response shapes:
  data360_get_data          → payload.data[], payload.metadata
  data360_rank_countries    → payload.year, payload.rankings[]
  data360_compare_countries → payload.snapshot.{year, rankings[]},
                               payload.time_series.series{} (when included)

All non-trivial disaggregation dimensions (sex, age, urbanisation,
comp_breakdown_1/2) are preserved in each record so downstream chart
selection can detect them and route accordingly.

Records use these column names:
  ref_area        str   ISO-3 code or regional aggregate (e.g. "ARG", "WLD")
  time_period     str   four-digit year string ("2022")
  value           float observed value
  unit_measure    str   unit code from the API (e.g. "PT", "USD_K_2015")
  sex             str   only present when non-trivial (e.g. "M", "F")
  age             str   only present when non-trivial
  urbanisation    str   only present when non-trivial
  comp_breakdown_1 str  only present when non-trivial
  comp_breakdown_2 str  only present when non-trivial
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DATA_TOOLS = {"data360_get_data", "data360_rank_countries", "data360_compare_countries"}

# API values that mean "all / not disaggregated / not applicable" — skip these
_TRIVIAL = {"_T", "_Z", ""}

# Disaggregation field names as they appear in the raw API observation
_DISAGG_FIELDS = (
    "SEX",
    "AGE",
    "URBANISATION",
    "COMP_BREAKDOWN_1",
    "COMP_BREAKDOWN_2",
)


def extract(tool_trace: list[dict]) -> dict[str, Any] | None:
    """Return a data context dict or None if no usable records were found.

    Return shape:
        indicator_code    str
        indicator_name    str
        database_id       str
        database_name     str
        definition        str
        periodicity       str
        unit              str
        source_url        str
        time_range        {start_year: int, end_year: int}
        area_codes        list[str]  (ordered by first appearance)
        columns           list[str]  (column names present in records)
        records           list[dict] (one dict per observation)
    """
    indicator_code: str | None = None
    indicator_name: str | None = None
    unit: str | None = None
    records: list[dict] = []
    seen: set[tuple] = set()

    # ── Pass 1: extract records from data tools ───────────────────────────────

    for entry in tool_trace:
        tool = entry.get("tool", "")
        if tool not in _DATA_TOOLS:
            continue

        payload = _parse_result(entry.get("result"))
        if not payload:
            continue

        args = entry.get("arguments", {})
        entry_code = args.get("indicator_id", "")

        # Anchor to the first indicator seen; skip unrelated later calls
        if not indicator_code and entry_code:
            indicator_code = entry_code
        if indicator_code and entry_code and entry_code != indicator_code:
            continue

        if tool == "data360_get_data":
            meta = payload.get("metadata") or {}
            indicator_name = indicator_name or meta.get("name")
            unit = unit or meta.get("measurement_unit")
            if not indicator_code:
                indicator_code = meta.get("idno") or entry_code
            _process_get_data(payload, records, seen, unit)

        elif tool == "data360_rank_countries":
            indicator_name = indicator_name or payload.get("indicator")
            unit = unit or payload.get("unit_measure") or payload.get("unit")
            _process_ranking(payload, records, seen, unit)

        elif tool == "data360_compare_countries":
            indicator_name = indicator_name or payload.get("indicator")
            unit = unit or payload.get("unit_measure") or payload.get("unit")
            _process_compare(payload, records, seen, unit)

    if not records:
        logger.info("[data_context] no records found in trace")
        return None

    # ── Pass 2: enrich indicator metadata from search results ─────────────────

    database_id: str | None = None
    database_name: str | None = None
    definition: str | None = None
    periodicity: str | None = None

    if indicator_code:
        parts = indicator_code.split("_")
        database_id = "_".join(parts[:2]) if len(parts) >= 2 else indicator_code

    for entry in tool_trace:
        if entry.get("tool") != "data360_search_indicators":
            continue
        payload = _parse_result(entry.get("result"))
        if not payload:
            continue
        for item in payload.get("indicators", []):
            if item.get("idno") == indicator_code:
                database_name = database_name or item.get("database_name")
                database_id = database_id or item.get("database_id")
                definition = definition or item.get("truncated_definition")
                periodicity = periodicity or item.get("periodicity")
                break

    # ── Derive columns list and summary fields ────────────────────────────────

    all_keys: set[str] = set()
    for r in records:
        all_keys.update(r.keys())

    # Ordered column list: core dims first, then disagg dims
    columns: list[str] = []
    for col in ["ref_area", "time_period", "value", "unit_measure"]:
        if col in all_keys:
            columns.append(col)
    for col in ["sex", "age", "urbanisation", "comp_breakdown_1", "comp_breakdown_2"]:
        if col in all_keys:
            columns.append(col)

    years = sorted({r["time_period"] for r in records if r.get("time_period")})
    area_codes = list(dict.fromkeys(r["ref_area"] for r in records))

    logger.info(
        "[data_context] indicator=%s areas=%d years=%s-%s disagg=%s",
        indicator_code,
        len(area_codes),
        years[0] if years else None,
        years[-1] if years else None,
        [c for c in columns if c not in ("ref_area", "time_period", "value", "unit_measure")] or "none",
    )

    return {
        "indicator_code": indicator_code or "",
        "indicator_name": indicator_name or indicator_code or "",
        "database_id": database_id or "",
        "database_name": database_name or "",
        "definition": definition or "",
        "periodicity": periodicity or "",
        "unit": unit or "",
        "source_url": (
            f"https://data360.worldbank.org/en/indicator/{indicator_code}"
            if indicator_code
            else ""
        ),
        "time_range": {
            "start_year": int(years[0]) if years else None,
            "end_year": int(years[-1]) if years else None,
        },
        "area_codes": area_codes,
        "columns": columns,
        "records": records,
    }


# ── Tool-specific extractors ──────────────────────────────────────────────────


def _process_get_data(
    payload: dict,
    records: list,
    seen: set,
    fallback_unit: str | None,
) -> None:
    meta_unit = (payload.get("metadata") or {}).get("measurement_unit") or fallback_unit or ""

    for obs in payload.get("data") or []:
        ref_area = obs.get("REF_AREA", "")
        time_period_raw = obs.get("TIME_PERIOD", "")
        obs_value = obs.get("OBS_VALUE")

        if not ref_area or not time_period_raw:
            continue
        try:
            value = float(obs_value)
        except (TypeError, ValueError):
            continue

        record: dict = {
            "ref_area": ref_area,
            "time_period": str(time_period_raw)[:4],
            "value": value,
            "unit_measure": obs.get("UNIT_MEASURE") or meta_unit,
        }

        # Preserve non-trivial disaggregation dimensions
        for field in _DISAGG_FIELDS:
            v = obs.get(field, "")
            if v and v not in _TRIVIAL:
                record[field.lower()] = v

        _add(records, seen, record)


def _process_ranking(
    payload: dict,
    records: list,
    seen: set,
    fallback_unit: str | None,
) -> None:
    year_raw = payload.get("year", "")
    if not year_raw:
        logger.warning("[data_context] rank_countries result missing year, skipping")
        return

    time_period = str(year_raw)[:4]
    unit_measure = payload.get("unit_measure") or payload.get("unit") or fallback_unit or ""

    for row in payload.get("rankings") or []:
        ref_area = row.get("ref_area") or row.get("code", "")
        if not ref_area:
            continue
        obs_value = row.get("obs_value") if row.get("obs_value") is not None else row.get("value")
        try:
            value = float(obs_value)
        except (TypeError, ValueError):
            continue

        record = {
            "ref_area": ref_area,
            "time_period": time_period,
            "value": value,
            "unit_measure": unit_measure,
        }
        _add(records, seen, record)


def _process_compare(
    payload: dict,
    records: list,
    seen: set,
    fallback_unit: str | None,
) -> None:
    unit_measure = payload.get("unit_measure") or payload.get("unit") or fallback_unit or ""

    # Snapshot: single-year rankings
    snapshot = payload.get("snapshot") or {}
    year_raw = snapshot.get("year", "")
    if year_raw:
        time_period = str(year_raw)[:4]
        for row in snapshot.get("rankings") or []:
            ref_area = row.get("ref_area") or row.get("code", "")
            if not ref_area:
                continue
            obs_value = row.get("obs_value") if row.get("obs_value") is not None else row.get("value")
            try:
                value = float(obs_value)
            except (TypeError, ValueError):
                continue
            record = {
                "ref_area": ref_area,
                "time_period": time_period,
                "value": value,
                "unit_measure": unit_measure,
            }
            _add(records, seen, record)

    # Time series: compact format [time_period, obs_value, claim_id]
    time_series = payload.get("time_series") or {}
    series = time_series.get("series") or {}
    for ref_area, points in series.items():
        for point in points:
            if not isinstance(point, list) or len(point) < 2:
                continue
            try:
                ts_year = str(point[0])[:4]
                ts_value = float(point[1])
            except (ValueError, TypeError):
                continue
            record = {
                "ref_area": ref_area,
                "time_period": ts_year,
                "value": ts_value,
                "unit_measure": unit_measure,
            }
            _add(records, seen, record)


def _add(records: list, seen: set, record: dict) -> None:
    """Append record if not already seen. Dedup key covers all dimension fields."""
    key = tuple(sorted(
        (k, v) for k, v in record.items() if k != "value"
    ))
    if key in seen:
        return
    seen.add(key)
    records.append(record)


def _parse_result(result: Any) -> dict | list | None:
    if isinstance(result, dict):
        text = result.get("text", "")
    elif isinstance(result, str):
        text = result
    else:
        return None
    if not isinstance(text, str):
        return None
    if text.startswith("root="):
        text = text[5:]
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
