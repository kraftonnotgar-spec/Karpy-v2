from __future__ import annotations

from karpy_platform.core.chart.base import BaseChart
from karpy_platform.core.chart.charts import AreaChart, BarChart, DonutChart, LineChart


class ChartBuilder:
    registry = {
        "area": AreaChart,
        "bar": BarChart,
        "donut": DonutChart,
        "line": LineChart,
    }

    def create(self, chart_class: str | type[BaseChart]) -> BaseChart:
        if isinstance(chart_class, str):
            chart_type = chart_class.lower().removesuffix("chart")
            if chart_type not in self.registry:
                raise ValueError(f"Chart class with name {chart_class} does not exist.")
            return self.registry[chart_type]()

        if not issubclass(chart_class, BaseChart):
            raise TypeError("chart_class must inherit from BaseChart")

        return chart_class()


chart_builder = ChartBuilder()
