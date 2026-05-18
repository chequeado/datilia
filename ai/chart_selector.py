"""AI chart type selector.

Receives the actual columns and cardinalities of the extracted dataset,
and returns a fully-specified ChartParams — strategy name plus concrete
column assignments for every visual encoding channel.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from asgiref.sync import async_to_sync
from openai import AsyncOpenAI
from pydantic import BaseModel

import ai.llm_client as llm_client

logger = logging.getLogger(__name__)

_INSTRUCTIONS = """\
You choose the best Vega-Lite chart type for a journalistic data visualization.
You will receive:
- The original claim the journalist is fact-checking
- The final text produced by the research agent (the actual finding)
- A description of the dataset's columns and cardinalities

Your goal is to pick the strategy that best communicates the story in the claim and finding.
You must assign each visual encoding channel to a real column name from the data.

Output fields:
- strategy, x_field, y_field, color_field, facet_field, highlight, top_n: chart type and encoding (see below)
- title: override the chart title (e.g. if the user asks to translate it or rewrite it); null to keep the default
- subtitle: override the chart subtitle (e.g. if the user asks to translate it or rewrite it); null to keep the default

Available strategies:
- "top_k"               Horizontal bars, top-N areas by value — ranking story, single year
- "top_k_others"        Horizontal bars, top-N + aggregated "Otros" bar — ranking where one specific area needs to be shown even if outside top-N
- "line"                Line chart, no markers — dense time series (many years or many areas)
- "line_dots"           Line + point markers — sparse annual data (≤15 years, ≤4 areas), each point matters
- "cross_sectional"     Horizontal bars — single year, few areas (≤8), direct comparison
- "distribution"        Strip/tick chart — single year, many areas (>8), spread/distribution is the story
- "breakdown_comparison" Grouped bars — one disaggregation dimension (sex/age/urbanisation), ≤4 areas, single year
- "small_multiples"     Faceted panels — disaggregation across time, or 2+ disagg dims, or breakdown + many areas
- "stacked_bar"         Stacked bars over time — parts-of-a-whole composition (age groups, causes within a country), ≤5 stack slices

Column assignment rules:
- x_field: dimension on the X axis (time_period for temporal charts; ref_area or disagg dim for categorical)
- y_field: always "value"
- color_field: field for color/series differentiation (ref_area, sex, age, urbanisation, etc.) — null if single series
- facet_field: only for small_multiples — field used to split into panels — null otherwise
- highlight: ISO-3 code of a specific area to visually emphasize if the claim focuses on one country — null otherwise
- top_n: number of bars for top_k / top_k_others, chosen so the highlighted area is always included — null for all other strategies

Decision process — follow in order:

STEP 1 — Read the claim and final_text for story cues. These signals should drive your choice:
- Ranking language ("biggest", "leads", "highest", "top N", "mayor", "primero") → prefer top_k or top_k_others
- One country vs. the world or a region ("Argentina compared to", "how does X rank", "Argentina frente a") → prefer top_k_others, set highlight
- Spread/distribution language ("varies widely", "gap", "unequal", "range", "dispersión") → prefer distribution
- Change-over-time language ("rose", "fell", "grew", "since", "trend", "over the last N years", "creció", "cayó") → prefer line or line_dots
- Composition/breakdown language ("share of", "driven by", "breakdown", "proportion", "participación") → prefer stacked_bar (disagg over time) or breakdown_comparison/small_multiples (disagg across areas)
- If the claim names a specific country → set highlight to its ISO-3 code

STEP 2 — Validate against data shape and resolve the final choice:

A) Disaggregation present (sex/age/urbanisation column with >1 value):
   - time_period has >1 value → "small_multiples" (x_field = time_period, color_field = disagg dim, facet_field = ref_area if ≤6 areas, otherwise facet_field = disagg dim, color_field = ref_area)
   - time_period has 1 value AND ≤4 areas → "breakdown_comparison" (x_field = ref_area, color_field = disagg dim)
   - time_period has 1 value AND >4 areas → "small_multiples"
   - Exception: composition cue present AND disagg dim represents parts-of-a-whole (age groups, causes) AND ≤5 ref_areas → "stacked_bar" (x_field = time_period, color_field = disagg dim)

B) No disaggregation, time series (time_period has >1 value):
   - ≤4 areas AND ≤15 years → "line_dots"
   - otherwise → "line"

C) No disaggregation, cross-sectional (time_period has 1 value):
   - ≤8 areas → "cross_sectional"
   - >8 areas: use claim cues to choose —
     - ranking cue → "top_k" (or "top_k_others" if highlight is set)
     - distribution/spread cue → "distribution"
     - no strong cue → "top_k"

top_k vs top_k_others: use top_k_others when highlight is set (so the highlighted area always appears even if outside top-N); use top_k when no specific area is emphasized. Set top_n so the highlighted area is included.

Threshold guidance: if the data sits near a threshold (e.g. 7 or 9 areas when threshold is 8), prefer the simpler chart.

Sort order: sort bars descending by value for bar charts, unless the claim implies a natural order.

Return only valid JSON matching the schema. No explanation.\
"""


class ChartParams(BaseModel):
    strategy: Literal[
        "top_k",
        "top_k_others",
        "line",
        "line_dots",
        "cross_sectional",
        "distribution",
        "breakdown_comparison",
        "small_multiples",
        "stacked_bar",
    ]
    x_field: str
    y_field: str
    color_field: str | None = None
    facet_field: str | None = None
    highlight: str | None = None
    top_n: int | None = None
    title: str | None = None
    subtitle: str | None = None


def _describe_data(data_context: dict[str, Any]) -> str:
    """Build a compact natural-language description of the dataset for the LLM."""
    records = data_context.get("records", [])
    columns = data_context.get("columns", [])
    if not records:
        return "No data available."

    lines: list[str] = []
    for col in columns:
        values = [r[col] for r in records if col in r]
        unique = list(dict.fromkeys(values))
        n = len(unique)

        if col == "value":
            nums = [v for v in values if isinstance(v, (int, float))]
            if nums:
                lines.append(
                    f"- value (float): range {min(nums):.2f} to {max(nums):.2f}"
                )
        elif col == "time_period":
            sorted_years = sorted(set(unique))
            if len(sorted_years) > 1:
                lines.append(
                    f"- time_period (str): {n} unique values — {sorted_years[0]} to {sorted_years[-1]}"
                )
            else:
                lines.append(f"- time_period (str): 1 unique value — {sorted_years[0]}")
        elif col == "unit_measure":
            sample = unique[0] if unique else ""
            lines.append(f"- unit_measure (str): {sample!r}")
        else:
            sample = ", ".join(str(v) for v in unique[:8])
            suffix = f" (… +{n - 8} more)" if n > 8 else ""
            lines.append(f"- {col} (str): {n} unique values — {sample}{suffix}")

    return "\n".join(lines)


async def select_async(
    claim: str,
    data_context: dict[str, Any],
    *,
    final_text: str = "",
    correction: str | None = None,
) -> ChartParams:
    indicator_name = data_context.get("indicator_name", "")
    unit = data_context.get("unit", "")
    data_description = _describe_data(data_context)

    time_range = data_context.get("time_range", {})
    start_year = time_range.get("start_year")
    end_year = time_range.get("end_year")
    year_label = (
        str(start_year) if start_year == end_year
        else f"{start_year}–{end_year}"
    ) if start_year else ""
    current_subtitle = f"{year_label} · {unit}" if unit else year_label

    unit_note = f" (unit: {unit})" if unit else ""
    finding_block = f"Finding (agent's conclusion):\n{final_text}\n\n" if final_text else ""
    correction_block = f"User correction request:\n{correction}\n\n" if correction else ""
    current_title_block = (
        f"Current chart title: {indicator_name}\nCurrent chart subtitle: {current_subtitle}\n\n"
        if correction else ""
    )
    user_msg = (
        f"Claim: {claim}\n\n"
        f"{finding_block}"
        f"{correction_block}"
        f"{current_title_block}"
        f"Indicator: {indicator_name}{unit_note}\n\n"
        f"Dataset columns:\n{data_description}"
    )

    client = AsyncOpenAI()
    response = await client.beta.chat.completions.parse(
        model=llm_client.MODEL,
        messages=[
            {"role": "system", "content": _INSTRUCTIONS},
            {"role": "user", "content": user_msg},
        ],
        response_format=ChartParams,
        temperature=0,
    )

    result = response.choices[0].message.parsed
    logger.info(
        "[chart_selector] strategy=%s x=%s y=%s color=%s facet=%s highlight=%s top_n=%s",
        result.strategy,
        result.x_field,
        result.y_field,
        result.color_field,
        result.facet_field,
        result.highlight,
        result.top_n,
    )
    return result


select = async_to_sync(select_async)
