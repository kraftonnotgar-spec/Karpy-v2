from __future__ import annotations

from typing import Any

from karpy_platform.core.chart.base import BaseChart
from karpy_platform.core.chart.types import ChartTypes


class Chart(BaseChart):
    chart_type = ChartTypes.LINE

    def default_options(self) -> dict[str, Any]:
        return {
            "xkey": [],
            "ykeys": [],
            "labels": [],
            "ymax": "auto",
            "ymin": 0,
            "hideHover": "auto",
            "axes": True,
            "grid": True,
            "gridTextColor": "#888",
            "gridTextSize": "12",
            "gridTextFamily": "sans-serif",
            "gridTextWeight": "normal",
            "resize": False,
            "rangeSelect": None,
            "rangeSelectColor": "#eef",
            "padding": 25,
            "numLines": 5,
            "events": [],
            "eventStrokeWidth": 1,
            "eventLineColors": ["#005a04", "#ccffbb", "#3a5f0b", "#005502"],
            "goals": [],
            "goalStrokeWidth": 1,
            "goalLineColors": ["#666633", "#999966", "#cc6666", "#663333"],
            "parseTime": True,
            "postUnits": "",
            "preUnits": "",
            "xLabelAngle": 0,
        }


class LineChart(Chart):
    chart_type = ChartTypes.LINE

    def default_options(self) -> dict[str, Any]:
        return {
            **super().default_options(),
            "lineColors": ["#0b62a4", "#7A92A3", "#4da74d", "#afd8f8", "#edc240", "#cb4b4b", "#9440ed"],
            "lineWidth": 3,
            "pointSize": 4,
            "pointFillColors": [],
            "pointStrokeColors": [],
            "smooth": True,
            "xLabels": [],
        }


class BarChart(Chart):
    chart_type = ChartTypes.BAR

    def default_options(self) -> dict[str, Any]:
        return {
            **super().default_options(),
            "barSizeRatio": 0.75,
            "barGap": 3,
            "barOpacity": 1.0,
            "barRadius": [0, 0, 0, 0],
            "xLabelMargin": 50,
            "barColors": ["#0b62a4", "#7a92a3", "#4da74d", "#afd8f8", "#edc240", "#cb4b4b", "#9440ed"],
            "stacked": True,
        }


class AreaChart(Chart):
    chart_type = ChartTypes.AREA

    def default_options(self) -> dict[str, Any]:
        return {
            **super().default_options(),
            "fillOpacity": "auto",
            "behaveLikeLine": False,
            "pointFillColors": [],
            "pointStrokeColors": [],
            "lineColors": [],
        }


class DonutChart(Chart):
    chart_type = ChartTypes.DONUT

    def default_options(self) -> dict[str, Any]:
        return {
            "data": [],
            "colors": ["#0B62A4", "#3980B5", "#679DC6", "#95BBD7", "#B0CCE1", "#095791", "#095085", "#083E67", "#052C48", "#042135"],
            "backgroundColor": "#FFFFFF",
            "labelColor": "#000000",
        }
