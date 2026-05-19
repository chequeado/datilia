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
You choose the best chart type for a journalistic data visualization.
You will receive:
- The original claim the journalist is fact-checking
- The finding (agent's conclusion) — the actual text that will accompany the chart
- A description of the dataset's columns and cardinalities

Your goal is to pick the strategy that best communicates the story in the claim and finding, and also tweak axis values to show the relevant data to the finding or overall point of the final text.
You must assign each visual encoding channel to a real column name from the data.

Output fields:
- strategy, x_field, y_field, color_field, facet_field, highlight, top_n: chart type and encoding (see below)
- title: chart title in the claim's language (Spanish by default). Indicator name.
- subtitle: time range and unit, adapted to the claim language.

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
- highlight: list of ISO-3 codes to visually emphasize (each gets a distinct color, everything else grayed out) — use when the claim or finding focuses on one or a few specific countries — null otherwise
- top_n: number of bars for top_k / top_k_others, chosen so the highlighted area is always included — null for all other strategies

Decision process:

Read the claim and the finding together to understand the editorial intent — what a reader needs to see to evaluate the claim. Then check what the data can actually support. Choose the chart that best serves the intent within the data's constraints.

EDITORIAL INTENT → NATURAL CHART (what you want to show):

- Subject's position among peers (ranking, who is first/last) → top_k_others with highlight, or top_k
- Direct comparison between a few named entities → cross_sectional (≤8) or top_k_others with highlight (>8)
- Trajectory of one or few entities over time → line_dots (sparse) or line (dense/many series)
- Where subject falls within a large group's spread → distribution (spread is the story) or top_k_others (rank is the story)
- Which entity changed the most across a period → bars of computed variation; if only raw multi-year data is available, rank by latest year as best approximation
- Composition (parts of a whole, breakdown by sex/age/category) → stacked_bar (over time) or breakdown_comparison (single year, few areas)
- Long-run historical arc of a single entity → line or line_dots for that entity alone

DATA CONSTRAINTS → WHAT THE DATA CAN SUPPORT:

- Disaggregation present (sex/age/urbanisation with >1 value):
  - time_period >1 value → small_multiples
  - time_period = 1 value, ≤4 areas → breakdown_comparison
  - time_period = 1 value, >4 areas → small_multiples
  - Exception: composition intent + disagg dim is parts-of-a-whole + ≤5 ref_areas → stacked_bar

- No disaggregation, multiple time periods:
  - ≤4 areas AND ≤15 years → line_dots
  - otherwise → line

- No disaggregation, single time period:
  - ≤8 areas → cross_sectional
  - >8 areas → top_k or top_k_others

RESOLVING INTENT VS. CONSTRAINTS:

When the editorial intent and data shape point to different charts, find the closest match — the chart that serves the story as well as the data allows. For example: a ranking story with multi-year data should still use a bar chart at the latest year, not default to a line chart just because multiple years exist.

top_k vs top_k_others: use top_k_others when a specific subject is highlighted; top_k otherwise. Set top_n so the highlighted area is always included.

COMPARABILITY RULE: If a Limitation note states the data should not be used for cross-country comparison, OR if the indicator name or definition implies each country uses its own national methodology (making absolute values inherently non-comparable), avoid cross_sectional/top_k/top_k_others/distribution/breakdown_comparison. Use line or line_dots with color separation instead, showing each country's own trend.

Threshold guidance: near a threshold (e.g. 7 or 9 areas when threshold is 8), prefer the simpler chart.

If the claim or finding focuses on specific countries, set highlight to a list of their ISO-3 codes (usually 1–3 items).
Sort bars descending by value unless the claim implies a natural order.

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
    highlight: list[str] | None = None
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
    limitation: str | None = None,
) -> ChartParams:
    indicator_name = data_context.get("indicator_name", "")
    unit = data_context.get("unit", "")
    limitation = limitation or data_context.get("limitation") or None
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
    limitation_block = f"Limitation: {limitation}\n\n" if limitation else ""
    current_title_block = (
        f"Current chart title: {indicator_name}\nCurrent chart subtitle: {current_subtitle}\n\n"
        if correction else ""
    )
    user_msg = (
        f"Claim: {claim}\n\n"
        f"{finding_block}"
        f"{correction_block}"
        f"{limitation_block}"
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
