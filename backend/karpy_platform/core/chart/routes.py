from __future__ import annotations

from fastapi import APIRouter

from karpy_platform.core.chart.builder import chart_builder

router = APIRouter()


@router.get("/chart/types")
async def list_chart_types():
    return {
        "types": [
            {"name": "Line", "key": "line"},
            {"name": "Bar", "key": "bar"},
            {"name": "Area", "key": "area"},
            {"name": "Donut", "key": "donut"},
        ]
    }


@router.get("/chart/preview/{chart_type}")
async def preview_chart(chart_type: str):
    chart = chart_builder.create(chart_type)

    if chart_type.lower().removesuffix("chart") == "donut":
        chart.data([
            {"label": "Published", "value": 64},
            {"label": "Draft", "value": 18},
            {"label": "Pending", "value": 8},
        ])
    else:
        chart.xkey("period").ykeys(["visits", "signups"]).labels(["Visits", "Signups"]).data([
            {"period": "2026-01", "visits": 120, "signups": 18},
            {"period": "2026-02", "visits": 160, "signups": 24},
            {"period": "2026-03", "visits": 210, "signups": 39},
        ])

    return {
        "type": chart.chart_type.value,
        "element": chart.get_element_id(),
        "options": chart.to_array(),
        "json": chart.to_json(),
        "html": chart.render_chart(),
    }
