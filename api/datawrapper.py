import csv
import io
import logging

import httpx
from django.utils import timezone

from config import settings

logger = logging.getLogger(__name__)

_DW_BASE = "https://api.datawrapper.de"

_STRATEGY_TO_TYPE = {
    "top_k":                "d3-bars",
    "top_k_others":         "d3-bars",
    "cross_sectional":      "d3-bars",
    "distribution":         "d3-scatter",
    "line":                 "d3-lines",
    "line_dots":            "d3-lines",
    "stacked_bar":          "d3-bars-stacked",
    "breakdown_comparison": "d3-bars-grouped",
    "small_multiples":      "d3-lines",
}


def _headers():
    return {
        "Authorization": f"Bearer {settings.DATAWRAPPER_API_KEY}",
        "Accept": "application/json",
    }


def _prepare_csv(data_ctx, chart_selection: str) -> str:
    records = data_ctx.records
    strategy = chart_selection.strategy
    x_field = chart_selection.x_field
    color_field = chart_selection.color_field
    top_n = chart_selection.top_n

    if not records:
        return ""

    buf = io.StringIO()

    if strategy in ("top_k", "top_k_others", "cross_sectional", "distribution"):
        # Cross-sectional: one row per x_field value using the latest year available
        latest_val: dict[str, float | None] = {}
        latest_year: dict[str, str] = {}
        for r in records:
            key = str(r.get(x_field, ""))
            val = r.get("value")
            year = str(r.get("time_period", ""))
            if key and (key not in latest_year or year > latest_year[key]):
                latest_val[key] = val
                latest_year[key] = year

        rows = [
            {x_field: k, "value": v}
            for k, v in latest_val.items()
            if v is not None
        ]
        rows.sort(key=lambda r: r["value"], reverse=True)
        if top_n:
            rows = rows[:top_n]

        writer = csv.DictWriter(buf, fieldnames=[x_field, "value"])
        writer.writeheader()
        writer.writerows(rows)

    elif strategy in ("line", "line_dots", "stacked_bar"):
        # Time series: pivot to wide — rows = time_period, cols = one per series
        if color_field:
            series = sorted({str(r.get(color_field, "")) for r in records if r.get(color_field)})
            times = sorted({str(r.get(x_field, "")) for r in records if r.get(x_field)})
            idx: dict[str, dict[str, object]] = {t: {} for t in times}
            for r in records:
                t = str(r.get(x_field, ""))
                s = str(r.get(color_field, ""))
                if t and s:
                    idx[t][s] = r.get("value", "")
            writer = csv.DictWriter(buf, fieldnames=[x_field] + series)
            writer.writeheader()
            for t in times:
                row: dict = {x_field: t}
                for s in series:
                    row[s] = idx[t].get(s, "")
                writer.writerow(row)
        else:
            rows = sorted(
                [{"time": r.get(x_field, ""), "value": r.get("value", "")} for r in records],
                key=lambda r: str(r["time"]),
            )
            writer = csv.DictWriter(buf, fieldnames=["time", "value"])
            writer.writeheader()
            writer.writerows(rows)

    elif strategy in ("breakdown_comparison", "small_multiples"):
        # Pivot color_field into columns, x_field as row key
        if color_field:
            cats = sorted({str(r.get(x_field, "")) for r in records if r.get(x_field)})
            series = sorted({str(r.get(color_field, "")) for r in records if r.get(color_field)})
            idx = {c: {} for c in cats}
            for r in records:
                c = str(r.get(x_field, ""))
                s = str(r.get(color_field, ""))
                if c and s:
                    idx[c][s] = r.get("value", "")
            writer = csv.DictWriter(buf, fieldnames=[x_field] + series)
            writer.writeheader()
            for c in cats:
                row = {x_field: c, **{s: idx[c].get(s, "") for s in series}}
                writer.writerow(row)
        else:
            writer = csv.DictWriter(buf, fieldnames=data_ctx.columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)

    else:
        writer = csv.DictWriter(buf, fieldnames=data_ctx.columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    return buf.getvalue()


def create_and_publish(data_ctx, chart_selection) -> dict:
    """Create, upload data, and publish a Datawrapper chart. Returns chart metadata dict."""
    dw_type = _STRATEGY_TO_TYPE.get(chart_selection.strategy, "d3-bars")
    csv_data = _prepare_csv(data_ctx, chart_selection)

    with httpx.Client(base_url=_DW_BASE, headers=_headers(), timeout=30) as client:
        year_parts = [str(y) for y in [data_ctx.start_year, data_ctx.end_year] if y]
        subtitle_parts = [("–".join(year_parts) if year_parts else ""), data_ctx.unit or ""]
        subtitle = " · ".join(p for p in subtitle_parts if p)

        resp = client.post("/v3/charts", json={
            "type": dw_type,
            "title": data_ctx.indicator_name,
            "metadata": {
                "describe": {
                    "source-name": data_ctx.database_name,
                    "source-url": data_ctx.source_url or "",
                    "intro": data_ctx.definition[:300] if data_ctx.definition else "",
                    "byline": subtitle,
                },
            },
        })
        resp.raise_for_status()
        chart_id = resp.json()["id"]
        logger.info("[datawrapper] created chart_id=%s type=%s", chart_id, dw_type)

        resp = client.put(
            f"/v3/charts/{chart_id}/data",
            content=csv_data.encode("utf-8"),
            headers={"Content-Type": "text/csv; charset=utf-8"},
        )
        resp.raise_for_status()

        resp = client.post(f"/v3/charts/{chart_id}/publish")
        if not resp.is_success:
            logger.error(
                "[datawrapper] publish failed chart_id=%s status=%s body=%s",
                chart_id, resp.status_code, resp.text,
            )
        resp.raise_for_status()
        publish_resp = resp.json()

    chart_url = f"https://datawrapper.dwcdn.net/{chart_id}/1/"
    embed_code = (
        publish_resp
        .get("metadata", {})
        .get("publish", {})
        .get("embed-codes", {})
        .get("embed-method-iframe", "")
    )

    logger.info("[datawrapper] published chart_id=%s url=%s", chart_id, chart_url)
    return {
        "chart_id": chart_id,
        "chart_url": chart_url,
        "embed_code": embed_code,
        "published_at": timezone.now(),
    }
