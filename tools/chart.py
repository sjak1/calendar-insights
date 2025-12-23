"""
Chart formatting utilities for Highcharts.
"""


def format_chart(chart_type, title, x_axis_data, series_data, y_axis_title=None):
    """
    Generate Highcharts configuration JSON for frontend rendering.
    
    Args:
        chart_type: Type of chart (bar, column, line, pie, area)
        title: Chart title
        x_axis_data: List of category labels for x-axis
        series_data: List of series objects with 'name' and 'data' keys
        y_axis_title: Optional y-axis label
    
    Returns:
        Dict with type='highcharts' and config for frontend to render
    
    Reference: https://api.highcharts.com/highcharts/
    """
    # Base config following Highcharts API structure
    highcharts_config = {
        "chart": {
            "type": chart_type
        },
        "title": {
            "text": title
        },
        "xAxis": {
            "categories": x_axis_data,
            "crosshair": True
        },
        "yAxis": {
            "min": 0,
            "title": {
                "text": y_axis_title or "Value"
            }
        },
        "tooltip": {
            "shared": True
        },
        "series": series_data,
        "plotOptions": {},
        "legend": {
            "enabled": len(series_data) > 1 if series_data else False
        },
        "credits": {
            "enabled": False
        }
    }
    
    # Chart-type specific plotOptions
    if chart_type in ["bar", "column"]:
        highcharts_config["plotOptions"][chart_type] = {
            "dataLabels": {
                "enabled": True
            },
            "borderRadius": 3
        }
    elif chart_type == "line":
        highcharts_config["plotOptions"]["line"] = {
            "dataLabels": {
                "enabled": True
            },
            "marker": {
                "enabled": True
            }
        }
    elif chart_type == "area":
        highcharts_config["plotOptions"]["area"] = {
            "fillOpacity": 0.5
        }
    elif chart_type == "pie":
        # Pie charts need data in {name, y} format per Highcharts spec
        if series_data and len(series_data) > 0:
            pie_data = []
            for i, category in enumerate(x_axis_data):
                value = series_data[0]["data"][i] if i < len(series_data[0]["data"]) else 0
                pie_data.append({"name": category, "y": value})
            highcharts_config["series"] = [{
                "name": series_data[0].get("name", "Data"),
                "colorByPoint": True,
                "data": pie_data
            }]
        # Pie charts don't use xAxis
        highcharts_config.pop("xAxis", None)
        highcharts_config["plotOptions"]["pie"] = {
            "allowPointSelect": True,
            "cursor": "pointer",
            "dataLabels": {
                "enabled": True,
                "format": "<b>{point.name}</b>: {point.y}"
            },
            "showInLegend": True
        }
        highcharts_config["legend"]["enabled"] = True
        highcharts_config["tooltip"] = {
            "pointFormat": "<b>{point.y}</b> ({point.percentage:.1f}%)"
        }
    
    return {
        "type": "highcharts",
        "config": highcharts_config
    }
