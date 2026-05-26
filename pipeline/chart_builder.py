import logging
from typing import Any

from pipeline import chart_spec as cs

logger = logging.getLogger(__name__)


def build(data_context: dict[str, Any], chart_params: Any) -> dict | None:
    """Build a Vega-Lite spec from data_context + chart_params.

    data_context is produced by pipeline.data_context.extract().
    chart_params is a ChartParams instance from ai.chart_selector.
    Column names (x_field, y_field, color_field, facet_field) come directly
    from chart_params — the AI resolved them against the actual dataset.
    """
    records = data_context.get("records", [])
    if not records:
        return None

    indicator_name = data_context.get("indicator_name", "")
    unit = data_context.get("unit") or None
    time_range = data_context.get("time_range", {})

    strategy = chart_params.strategy

    x_field    = chart_params.x_field
    y_field    = chart_params.y_field
    color_field = chart_params.color_field
    facet_field = chart_params.facet_field
    highlight   = chart_params.highlight
    top_n       = chart_params.top_n or 10

    start_year = time_range.get("start_year")
    end_year   = time_range.get("end_year")
    year_label = (
        str(start_year) if start_year == end_year
        else f"{start_year}–{end_year}"
    )

    _SNAPSHOT_STRATEGIES = {"cross_sectional", "distribution", "top_k", "top_k_others"}
    if strategy in _SNAPSHOT_STRATEGIES and end_year:
        snapshot_year = str(end_year)
        filtered = [r for r in records if str(r.get("time_period", "")) == snapshot_year]
        if filtered:
            records = filtered

    title = {
        "text": chart_params.title if chart_params.title else indicator_name,
        "subtitle": chart_params.subtitle if chart_params.subtitle else (f"{year_label} · {unit}" if unit else year_label),
    }

    logger.info(
        "[chart_builder] strategy=%s x=%s y=%s color=%s facet=%s indicator=%s",
        strategy, x_field, y_field, color_field, facet_field,
        data_context.get("indicator_code"),
    )

    if strategy == "top_k":
        spec = cs.build_topk_bar_spec(
            records, title, unit, x_field, y_field, color_field, highlight, top_n
        )
    elif strategy == "top_k_others":
        spec = cs.build_topk_others_spec(
            records, title, unit, x_field, y_field, color_field, highlight, top_n
        )
    elif strategy == "line":
        spec = cs.build_line_spec(
            records, title, unit, x_field, y_field, color_field, highlight, dots=False
        )
    elif strategy == "line_dots":
        spec = cs.build_line_spec(
            records, title, unit, x_field, y_field, color_field, highlight, dots=True
        )
    elif strategy == "cross_sectional":
        spec = cs.build_cross_sectional_spec(
            records, title, unit, x_field, y_field, color_field, highlight
        )
    elif strategy == "distribution":
        spec = cs.build_distribution_spec(
            records, title, unit, x_field, y_field, color_field, highlight
        )
    elif strategy == "breakdown_comparison":
        spec = cs.build_breakdown_comparison_spec(
            records, title, unit, x_field, y_field, color_field or x_field, highlight
        )
    elif strategy == "small_multiples":
        spec = cs.build_small_multiples_spec(
            records, title, unit, x_field, y_field, color_field,
            facet_field or x_field, highlight
        )
    elif strategy == "stacked_bar":
        spec = cs.build_stacked_bar_spec(
            records, title, unit, x_field, y_field, color_field or x_field, highlight
        )
    else:
        logger.warning("[chart_builder] unknown strategy %r, falling back to line", strategy)
        spec = cs.build_line_spec(
            records, title, unit, x_field, y_field, color_field, highlight, dots=True
        )

    return spec
