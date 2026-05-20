"""Pure Vega-Lite spec builders for Chequeado fact-check visualizations.

No I/O, no pandas, no async — fully unit-testable pure functions.
Style reference: World Bank Data Visualization Style Guide.

All builders accept explicit column-name parameters (x_field, y_field,
color_field, facet_field) rather than assuming "country"/"year"/"value".
The chart_builder module resolves those names from ChartParams before
calling these functions.

Supported strategies:
  top_k                Horizontal bars, top-N areas by value
  top_k_others         Horizontal bars, top-N + aggregated "Otros" bar
  line                 Line chart, no markers (dense time series)
  line_dots            Line + point markers (sparse time series)
  cross_sectional      Horizontal bars, single year, few areas
  distribution         Strip/tick chart, single year, many areas
  breakdown_comparison Grouped bars by disaggregation dimension (sex/age/urban)
  small_multiples      Faceted panels
  stacked_bar          Stacked bars over time
"""
from __future__ import annotations

# ── Style tokens ──────────────────────────────────────────────────────────────

CAT_COLORS: list[str] = [
    "#34A7F2",  # blue
    "#FF9800",  # orange
    "#664AB6",  # purple
    "#4EC2C0",  # teal
    "#F3578E",  # pink
    "#081079",  # navy
    "#0C7C68",  # dark green
    "#AA0000",  # red
    "#DDDA21",  # yellow
]

_GENDER_COLORS: dict[str, str] = {
    "F": "#FF9800",
    "M": "#664AB6",
    "_T": "#4EC2C0",
}

_TEXT = "#111111"
_TEXT_SUBTLE = "#666666"
_GRID = "#CED4DE"
_WHITE = "#FFFFFF"
_FONT = "Noto Sans, Arial, sans-serif"

_FIELD_LABELS: dict[str, str] = {
    "ref_area": "País/Área",
    "time_period": "Año",
    "value": "Valor",
    "unit_measure": "Unidad",
    "sex": "Sexo",
    "age": "Grupo de edad",
    "urbanisation": "Urbanización",
    "comp_breakdown_1": "Desglose 1",
    "comp_breakdown_2": "Desglose 2",
}


# ── Internal style helpers ────────────────────────────────────────────────────


def _schema() -> str:
    return "https://vega.github.io/schema/vega-lite/v5.json"


def _config() -> dict:
    return {
        "background": _WHITE,
        "font": _FONT,
        "title": {
            "fontSize": 16,
            "fontWeight": "bold",
            "color": _TEXT,
            "anchor": "start",
            "offset": 8,
            "subtitleFontSize": 12,
            "subtitleColor": _TEXT_SUBTLE,
            "subtitleFontWeight": "normal",
            "subtitlePadding": 4,
        },
        "axis": {
            "labelColor": _TEXT_SUBTLE,
            "labelFontSize": 12,
            "titleColor": _TEXT,
            "titleFontSize": 12,
            "titleFontWeight": "bold",
            "gridColor": _GRID,
            "gridDash": [4, 2],
            "gridWidth": 1,
            "domainColor": _GRID,
            "tickColor": _GRID,
            "tickCount": 5,
        },
        "legend": {
            "labelColor": _TEXT,
            "labelFontSize": 12,
            "labelFontWeight": "bold",
            "labelLimit": 200,
            "orient": "top",
            "direction": "horizontal",
        },
        "range": {"category": CAT_COLORS},
        "view": {"stroke": "transparent"},
        "line": {"strokeWidth": 3, "strokeCap": "round"},
        "point": {"size": 60, "stroke": _WHITE, "strokeWidth": 1},
        "bar": {"cornerRadiusTopLeft": 2, "cornerRadiusTopRight": 2},
    }


def _label_expr(unit: str | None) -> str:
    u = (unit or "").upper()
    prefix = "$" if ("$" in u or "USD" in u) else ""
    tiers = [("1e12", "t"), ("1e9", "b"), ("1e6", "m"), ("1e3", "k")]
    parts = [
        f"abs(datum.value)>={t} ? '{prefix}'+format(datum.value/{t},'.1f')+'{s}'"
        for t, s in tiers
    ]
    tail = (
        f" : abs(datum.value)>=10 ? '{prefix}'+format(datum.value,',.1f')"
        f" : '{prefix}'+format(datum.value,'.2f')"
    )
    return " : ".join(parts) + tail


def _tt_format(max_abs: float | None, unit: str | None) -> str:
    u = (unit or "").upper()
    if "%" in (unit or ""):
        return ".1f"
    if "$" in u or "USD" in u:
        return "$,.2f"
    if max_abs is None or max_abs < 1:
        return ".2f"
    if max_abs < 10:
        return ".1f"
    if max_abs < 1000:
        return ",.1f"
    return ",.3~s"


def _field_label(field: str) -> str:
    return _FIELD_LABELS.get(field, field.replace("_", " ").title())


def _tooltips(fields: list[str], y_field: str, val_fmt: str) -> list[dict]:
    tips = []
    for col in fields:
        tip: dict = {"field": col, "title": _field_label(col)}
        if col == "time_period":
            tip["type"] = "temporal"
            tip["timeUnit"] = "utcyear"
            tip["format"] = "%Y"
        elif col == y_field:
            tip["type"] = "quantitative"
            tip["format"] = val_fmt
        else:
            tip["type"] = "nominal"
        tips.append(tip)
    return tips


def _color_enc(color_field: str, highlight: list[str] | None = None, all_values: list[str] | None = None) -> dict:
    """Color encoding: field-based so Vega-Lite always generates a legend.

    With highlight: highlighted values get distinct palette colors, rest gray.
    Legend is filtered to show only highlighted entries.
    Without highlight: standard categorical palette, full legend.
    """
    if highlight and all_values and any(h in set(all_values) for h in highlight):
        highlight_set = {h: i for i, h in enumerate(highlight)}
        domain = all_values
        range_ = [CAT_COLORS[highlight_set[v] % len(CAT_COLORS)] if v in highlight_set else _GRID for v in all_values]
        return {
            "field": color_field,
            "type": "nominal",
            "scale": {"domain": domain, "range": range_},
            "legend": {
                "values": highlight,
                "orient": "top",
                "direction": "horizontal",
                "labelLimit": 120,
                "columns": 4,
            },
        }
    if color_field == "sex":
        domain = list(_GENDER_COLORS.keys())
        return {
            "field": color_field,
            "type": "nominal",
            "scale": {"domain": domain, "range": [_GENDER_COLORS[k] for k in domain]},
            "legend": {"orient": "top", "direction": "horizontal", "title": _field_label(color_field)},
        }
    return {
        "field": color_field,
        "type": "nominal",
        "scale": {"range": CAT_COLORS},
        "legend": {
            "orient": "top",
            "direction": "horizontal",
            "labelLimit": 120,
            "columns": 4,
        },
    }


def _value_axis(unit: str | None) -> dict:
    return {
        "title": None,
        "gridColor": _GRID,
        "gridDash": [4, 2],
        "labelColor": _TEXT_SUBTLE,
        "labelExpr": _label_expr(unit),
        "tickCount": 5,
    }


def _category_axis() -> dict:
    return {
        "title": None,
        "labelColor": _TEXT,
        "labelFontWeight": "bold",
        "labelLimit": 160,
    }


def _temporal_axis() -> dict:
    return {
        "title": None,
        "format": "%Y",
        "labelAngle": 0,
        "tickCount": 5,
        "gridColor": _GRID,
        "gridDash": [4, 2],
        "labelColor": _TEXT_SUBTLE,
    }


def _temporal_enc(field: str) -> dict:
    """Temporal X encoding that avoids UTC-offset year shift."""
    return {"field": field, "type": "temporal", "timeUnit": "utcyear", "axis": _temporal_axis()}


def _max_abs(records: list[dict], y_field: str) -> float | None:
    vals = [r[y_field] for r in records if isinstance(r.get(y_field), (int, float))]
    return max(abs(v) for v in vals) if vals else None


# ── Spec builders ─────────────────────────────────────────────────────────────


def build_topk_bar_spec(
    records: list[dict],
    title: str | dict,
    unit: str | None,
    x_field: str,
    y_field: str,
    color_field: str | None,
    highlight: str | None = None,
    top_n: int = 15,
) -> dict:
    """Horizontal bars: top_n areas by value descending."""
    rows = sorted(records, key=lambda r: r.get(y_field, 0), reverse=True)[:top_n]
    tt_fmt = _tt_format(_max_abs(rows, y_field), unit)
    tooltip_fields = list(dict.fromkeys([x_field, "time_period", y_field]))

    cf = color_field or x_field
    all_values = list(dict.fromkeys(r.get(cf) for r in rows if r.get(cf)))
    return {
        "$schema": _schema(),
        "title": title,
        "data": {"values": rows},
        "mark": {"type": "bar", "cornerRadiusTopRight": 3, "cornerRadiusBottomRight": 3},
        "encoding": {
            "y": {"field": x_field, "type": "nominal", "sort": f"-x", "axis": _category_axis()},
            "x": {
                "field": y_field,
                "type": "quantitative",
                "axis": _value_axis(unit),
                "scale": {"zero": True},
            },
            "color": _color_enc(cf, highlight, all_values),
            "tooltip": _tooltips(tooltip_fields, y_field, tt_fmt),
        },
        "width": 500,
        "height": max(180, len(rows) * 28),
        "config": _config(),
    }


def build_topk_others_spec(
    records: list[dict],
    title: str | dict,
    unit: str | None,
    x_field: str,
    y_field: str,
    color_field: str | None,
    highlight: str | None = None,
    top_n: int = 10,
) -> dict:
    """Horizontal bars: top_n areas + aggregated 'Otros' bar."""
    rows = sorted(records, key=lambda r: r.get(y_field, 0), reverse=True)
    top_rows = rows[:top_n]
    rest = rows[top_n:]

    display_rows = list(top_rows)
    if rest:
        ref_time = top_rows[0].get("time_period") if top_rows else None
        otros_value = sum(r[y_field] for r in rest if isinstance(r.get(y_field), (int, float))) / max(len(rest), 1)
        display_rows.append({"ref_area": "Otros (promedio)", x_field: "Otros (promedio)", "time_period": ref_time, y_field: otros_value})

    tt_fmt = _tt_format(_max_abs(display_rows, y_field), unit)
    order = [r[x_field] for r in display_rows]
    tooltip_fields = list(dict.fromkeys([x_field, "time_period", y_field]))

    all_values = [r[x_field] for r in display_rows if r.get(x_field)]
    if highlight:
        color_encoding: dict = _color_enc(x_field, highlight, all_values)
    else:
        otros_idx = next((i for i, v in enumerate(all_values) if v == "Otros (promedio)"), None)
        range_ = [CAT_COLORS[0]] * len(all_values)
        if otros_idx is not None:
            range_[otros_idx] = _TEXT_SUBTLE
        color_encoding = {
            "field": x_field,
            "type": "nominal",
            "scale": {"domain": all_values, "range": range_},
            "legend": None,
        }

    return {
        "$schema": _schema(),
        "title": title,
        "data": {"values": display_rows},
        "mark": {"type": "bar", "cornerRadiusTopRight": 3, "cornerRadiusBottomRight": 3},
        "encoding": {
            "y": {"field": x_field, "type": "nominal", "sort": order, "axis": _category_axis()},
            "x": {
                "field": y_field,
                "type": "quantitative",
                "axis": _value_axis(unit),
                "scale": {"zero": True},
            },
            "color": color_encoding,
            "tooltip": _tooltips(tooltip_fields, y_field, tt_fmt),
        },
        "width": 500,
        "height": max(180, len(display_rows) * 28),
        "config": _config(),
    }


def build_line_spec(
    records: list[dict],
    title: str | dict,
    unit: str | None,
    x_field: str,
    y_field: str,
    color_field: str | None,
    highlight: str | None = None,
    dots: bool = False,
) -> dict:
    """Line chart: multi-year time series."""
    tt_fmt = _tt_format(_max_abs(records, y_field), unit)
    tooltip_fields = list(dict.fromkeys(
        [f for f in [color_field, x_field, y_field] if f]
    ))

    mark: dict = {"type": "line", "strokeWidth": 3, "strokeCap": "round"}
    if dots:
        mark["point"] = {"filled": True, "size": 56}

    encoding: dict = {
        "x": _temporal_enc(x_field),
        "y": {
            "field": y_field,
            "type": "quantitative",
            "axis": _value_axis(unit),
            "scale": {"zero": False},
        },
        "tooltip": _tooltips(tooltip_fields, y_field, tt_fmt),
    }
    if color_field:
        all_values = list(dict.fromkeys(r.get(color_field) for r in records if r.get(color_field)))
        encoding["color"] = _color_enc(color_field, highlight, all_values)


    return {
        "$schema": _schema(),
        "title": title,
        "data": {"values": records},
        "mark": mark,
        "encoding": encoding,
        "width": 600,
        "height": 350,
        "config": _config(),
    }


def build_cross_sectional_spec(
    records: list[dict],
    title: str | dict,
    unit: str | None,
    x_field: str,
    y_field: str,
    color_field: str | None,
    highlight: str | None = None,
) -> dict:
    """Horizontal bars: single year, few areas, direct comparison."""
    rows = sorted(records, key=lambda r: r.get(y_field, 0), reverse=True)
    tt_fmt = _tt_format(_max_abs(rows, y_field), unit)
    tooltip_fields = list(dict.fromkeys([x_field, "time_period", y_field]))
    cf = color_field or x_field
    all_values = list(dict.fromkeys(r.get(cf) for r in rows if r.get(cf)))

    return {
        "$schema": _schema(),
        "title": title,
        "data": {"values": rows},
        "mark": {"type": "bar", "cornerRadiusTopRight": 3, "cornerRadiusBottomRight": 3},
        "encoding": {
            "y": {"field": x_field, "type": "nominal", "sort": "-x", "axis": _category_axis()},
            "x": {
                "field": y_field,
                "type": "quantitative",
                "axis": _value_axis(unit),
                "scale": {"zero": True},
            },
            "color": _color_enc(cf, highlight, all_values),
            "tooltip": _tooltips(tooltip_fields, y_field, tt_fmt),
        },
        "width": 500,
        "height": max(180, len(rows) * 28),
        "config": _config(),
    }


def build_distribution_spec(
    records: list[dict],
    title: str | dict,
    unit: str | None,
    x_field: str,
    y_field: str,
    color_field: str | None,
    highlight: str | None = None,
) -> dict:
    """Strip/tick chart: single year, many areas, distribution shape."""
    rows = sorted(records, key=lambda r: r.get(y_field, 0), reverse=True)
    tt_fmt = _tt_format(_max_abs(rows, y_field), unit)
    tooltip_fields = list(dict.fromkeys([x_field, "time_period", y_field]))
    cf = color_field or x_field
    all_values = list(dict.fromkeys(r.get(cf) for r in rows if r.get(cf)))

    layers: list[dict] = [
        {
            "mark": {"type": "tick", "thickness": 3, "bandSize": 18},
            "encoding": {
                "x": {
                    "field": y_field,
                    "type": "quantitative",
                    "axis": _value_axis(unit),
                },
                "y": {
                    "field": x_field,
                    "type": "nominal",
                    "sort": "-x",
                    "axis": _category_axis(),
                },
                "color": _color_enc(cf, highlight, all_values),
                "tooltip": _tooltips(tooltip_fields, y_field, tt_fmt),
            },
        }
    ]

    if highlight:
        for i, h in enumerate(highlight):
            matched = [r for r in records if r.get(x_field) == h]
            if matched:
                layers.append({
                    "mark": {"type": "rule", "color": CAT_COLORS[i % len(CAT_COLORS)], "strokeWidth": 2, "strokeDash": [5, 3]},
                    "encoding": {
                        "x": {"datum": matched[0][y_field], "type": "quantitative"},
                        "tooltip": [{"datum": h, "type": "nominal", "title": _field_label(x_field)}],
                    },
                })

    return {
        "$schema": _schema(),
        "title": title,
        "data": {"values": rows},
        "layer": layers,
        "width": 500,
        "height": max(250, len(rows) * 20),
        "config": _config(),
    }


def build_breakdown_comparison_spec(
    records: list[dict],
    title: str | dict,
    unit: str | None,
    x_field: str,
    y_field: str,
    color_field: str,
    highlight: str | None = None,
) -> dict:
    """Grouped bars: one breakdown dimension (sex/age/urbanisation) per area."""
    tt_fmt = _tt_format(_max_abs(records, y_field), unit)
    all_fields = list(dict.fromkeys([x_field, color_field, y_field, "time_period"]))
    tooltip_fields = [f for f in all_fields if f in {r_key for r in records for r_key in r}]

    return {
        "$schema": _schema(),
        "title": title,
        "data": {"values": records},
        "mark": {"type": "bar"},
        "encoding": {
            "x": {
                "field": x_field,
                "type": "nominal",
                "axis": {"title": None, "labelColor": _TEXT, "labelFontWeight": "bold"},
            },
            "xOffset": {"field": color_field, "type": "nominal"},
            "y": {
                "field": y_field,
                "type": "quantitative",
                "axis": _value_axis(unit),
                "scale": {"zero": True},
            },
            "color": _color_enc(color_field),
            "tooltip": _tooltips(tooltip_fields, y_field, tt_fmt),
        },
        "width": max(300, len({r[x_field] for r in records}) * 80),
        "height": 320,
        "config": _config(),
    }


def build_small_multiples_spec(
    records: list[dict],
    title: str | dict,
    unit: str | None,
    x_field: str,
    y_field: str,
    color_field: str | None,
    facet_field: str,
    highlight: str | None = None,
) -> dict:
    """Faceted panels: one panel per facet_field value, lines or bars inside."""
    tt_fmt = _tt_format(_max_abs(records, y_field), unit)
    n_facets = len({r[facet_field] for r in records if facet_field in r})

    inner: dict = {
        "mark": {"type": "line", "strokeWidth": 2, "point": {"filled": True, "size": 40}},
        "encoding": {
            "x": _temporal_enc(x_field),
            "y": {
                "field": y_field,
                "type": "quantitative",
                "axis": _value_axis(unit),
                "scale": {"zero": False},
            },
            "tooltip": _tooltips([x_field, y_field], y_field, tt_fmt),
        },
    }
    if color_field and color_field != facet_field:
        all_values = list(dict.fromkeys(r.get(color_field) for r in records if r.get(color_field)))
        inner["encoding"]["color"] = _color_enc(color_field, highlight, all_values)

    return {
        "$schema": _schema(),
        "title": title,
        "data": {"values": records},
        "facet": {
            "field": facet_field,
            "type": "nominal",
            "columns": min(3, n_facets),
            "header": {
                "labelFontWeight": "bold",
                "labelColor": _TEXT,
                "title": _field_label(facet_field),
                "titleColor": _TEXT,
            },
        },
        "spec": {**inner, "width": 220, "height": 160},
        "config": _config(),
    }


def build_stacked_bar_spec(
    records: list[dict],
    title: str | dict,
    unit: str | None,
    x_field: str,
    y_field: str,
    color_field: str,
    highlight: str | None = None,
) -> dict:
    """Stacked bars: time on X, color = breakdown field, stacked values."""
    tt_fmt = _tt_format(_max_abs(records, y_field), unit)
    tooltip_fields = list(dict.fromkeys([color_field, x_field, y_field]))
    all_values = list(dict.fromkeys(r.get(color_field) for r in records if r.get(color_field)))

    return {
        "$schema": _schema(),
        "title": title,
        "data": {"values": records},
        "mark": {"type": "bar"},
        "encoding": {
            "x": _temporal_enc(x_field),
            "y": {
                "field": y_field,
                "type": "quantitative",
                "axis": _value_axis(unit),
                "stack": True,
            },
            "color": _color_enc(color_field, highlight, all_values),
            "tooltip": _tooltips(tooltip_fields, y_field, tt_fmt),
        },
        "width": 500,
        "height": 300,
        "config": _config(),
    }
