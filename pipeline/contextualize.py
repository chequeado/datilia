import asyncio
import logging
from typing import Any

from ai.chart_selector import select_async as select_chart_params
from ai.tool_loop import _run_async as _tool_loop
from pipeline.chart_builder import build as build_chart
from pipeline.data_context import extract as extract_data_context

logger = logging.getLogger(__name__)


async def _run_async(claim: str, context: str | None, language: str, correction: str | None = None) -> dict[str, Any]:
    # Step 1: agentic tool loop — agent calls Data360 tools to research the claim
    loop_result = await _tool_loop(claim=claim, context=context, language=language, correction=correction)
    final_text: str = loop_result["final_text"]
    tool_trace: list[dict] = loop_result["tool_trace"]

    # Step 2: extract structured data context from the trace
    data_ctx = extract_data_context(tool_trace)

    if not data_ctx:
        logger.info("[contextualize] no data found in trace, not verifiable")
        return {
            "is_verifiable": False,
            "final_text": final_text,
            "tool_trace": tool_trace,
        }

    logger.info(
        "[contextualize] verifiable indicator=%s areas=%d years=%s-%s",
        data_ctx["indicator_code"],
        len(data_ctx["area_codes"]),
        data_ctx["time_range"]["start_year"],
        data_ctx["time_range"]["end_year"],
    )

    # Step 3: choose chart type via AI
    chart_params = await select_chart_params(claim, data_ctx, final_text=final_text)

    # Step 4: build Vega-Lite spec
    chart_spec = build_chart(data_ctx, chart_params)

    return {
        "is_verifiable": True,
        "final_text": final_text,
        "indicator_code": data_ctx["indicator_code"],
        "indicator_name": data_ctx["indicator_name"],
        "database_id": data_ctx["database_id"],
        "database_name": data_ctx["database_name"],
        "definition": data_ctx["definition"],
        "periodicity": data_ctx["periodicity"],
        "unit": data_ctx["unit"],
        "source_url": data_ctx["source_url"],
        "area_codes": data_ctx["area_codes"],
        "columns": data_ctx["columns"],
        "time_range": data_ctx["time_range"],
        "chart_spec": chart_spec,
        "chart_params": chart_params.model_dump(),
        "records": data_ctx["records"],
        "tool_trace": tool_trace,
    }


def run(claim: str, context: str | None, language: str, correction: str | None = None) -> dict[str, Any]:
    return asyncio.run(_run_async(claim, context, language, correction=correction))


async def _correct_chart_async(parent_data_ctx: dict[str, Any], claim: str, final_text: str, correction: str) -> dict[str, Any]:
    """Re-run only chart selection + build using an existing data context."""
    chart_params = await select_chart_params(claim, parent_data_ctx, final_text=final_text, correction=correction)
    chart_spec = build_chart(parent_data_ctx, chart_params)
    return {
        "is_verifiable": True,
        "final_text": final_text,
        "indicator_code": parent_data_ctx["indicator_code"],
        "indicator_name": parent_data_ctx["indicator_name"],
        "database_id": parent_data_ctx["database_id"],
        "database_name": parent_data_ctx["database_name"],
        "definition": parent_data_ctx["definition"],
        "periodicity": parent_data_ctx["periodicity"],
        "unit": parent_data_ctx["unit"],
        "source_url": parent_data_ctx["source_url"],
        "area_codes": parent_data_ctx["area_codes"],
        "columns": parent_data_ctx["columns"],
        "time_range": parent_data_ctx["time_range"],
        "chart_spec": chart_spec,
        "chart_params": chart_params.model_dump(),
        "records": parent_data_ctx["records"],
        "tool_trace": [],
    }


def correct_chart(parent_data_ctx: dict[str, Any], claim: str, final_text: str, correction: str) -> dict[str, Any]:
    return asyncio.run(_correct_chart_async(parent_data_ctx, claim, final_text, correction))


def correct_data(claim: str, context: str | None, language: str, correction: str) -> dict[str, Any]:
    return asyncio.run(_run_async(claim, context, language, correction=correction))
