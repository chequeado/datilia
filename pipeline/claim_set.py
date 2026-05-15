import json
import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Claim(BaseModel):
    claim_id: str
    indicator_code: str
    indicator_name: str
    country_code: str
    year: int
    value: float
    unit: str
    source_url: str
    policy: str  # "round_to_1dp" | "exact"


_DATA_TOOLS = {"data360_get_data", "data360_rank_countries", "data360_compare_countries"}


def build(tool_trace: list[dict]) -> list[Claim]:
    """Extract one Claim per data point from recognised data tool calls in the trace."""
    claims = []
    for entry in tool_trace:
        tool = entry.get("tool", "")
        if tool not in _DATA_TOOLS:
            continue
        payload = _parse_result(entry.get("result"))
        if not payload:
            continue

        if tool == "data360_get_data":
            claims.extend(_claims_from_get_data(entry, payload))
        elif tool in ("data360_rank_countries", "data360_compare_countries"):
            claims.extend(_claims_from_ranking(entry, payload))

    logger.info("[claim_set] extracted %d claims", len(claims))
    return claims


def _claims_from_get_data(entry: dict, payload: dict) -> list[Claim]:
    args = entry.get("arguments", {})
    metadata = payload.get("metadata", {})
    indicator_code = metadata.get("idno") or args.get("indicator_id", "")
    indicator_name = metadata.get("name") or indicator_code
    unit = metadata.get("measurement_unit", "")
    source_url = f"https://data360.worldbank.org/en/indicator/{indicator_code}"
    policy = "round_to_1dp" if "%" in unit else "exact"

    claims = []
    for obs in payload.get("data", []):
        try:
            value = float(obs["OBS_VALUE"])
            year = int(obs["TIME_PERIOD"])
        except (KeyError, ValueError, TypeError):
            continue
        country_code = obs.get("REF_AREA", args.get("country_code", ""))
        claim_id = obs.get("claim_id") or f"{indicator_code}_{country_code}_{year}"
        claims.append(Claim(
            claim_id=claim_id,
            indicator_code=indicator_code,
            indicator_name=indicator_name,
            country_code=country_code,
            year=year,
            value=value,
            unit=unit,
            source_url=source_url,
            policy=policy,
        ))
    return claims


def _claims_from_ranking(entry: dict, payload: dict) -> list[Claim]:
    args = entry.get("arguments", {})
    indicator_code = args.get("indicator_id", "")
    indicator_name = payload.get("indicator", indicator_code)
    unit = payload.get("unit", "")
    source_url = f"https://data360.worldbank.org/en/indicator/{indicator_code}"
    policy = "round_to_1dp" if "%" in unit else "exact"

    # data360_compare_countries wraps year+rankings under "snapshot"
    ranking_payload = payload.get("snapshot") or payload

    try:
        year = int(ranking_payload.get("year", 0))
    except (ValueError, TypeError):
        year = 0

    claims = []
    for row in ranking_payload.get("rankings", []):
        try:
            value = float(row["value"])
            country_code = row["code"]
        except (KeyError, ValueError, TypeError):
            continue
        claim_id = row.get("claim_id") or f"{indicator_code}_{country_code}_{year}"
        claims.append(Claim(
            claim_id=claim_id,
            indicator_code=indicator_code,
            indicator_name=indicator_name,
            country_code=country_code,
            year=year,
            value=value,
            unit=unit,
            source_url=source_url,
            policy=policy,
        ))
    return claims


def _parse_result(result: Any) -> dict | list | None:
    """Normalize the various shapes a tool result can take into a plain dict or list."""
    if isinstance(result, dict):
        text = result.get("text", "")
    elif isinstance(result, str):
        text = result
    else:
        return None

    text = text.lstrip("root=").strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("[pipeline] could not parse tool result: %r", text[:200])
        return None
