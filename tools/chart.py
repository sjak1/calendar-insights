"""
Chart formatting utilities for Highcharts.

Reference: https://www.highcharts.com/docs/
"""


def format_chart(
    chart_type,
    title,
    x_axis_data,
    series_data,
    y_axis_title=None,
    stacking=None,
    subtitle=None,
    heatmap_data=None,
    y_axis_data=None,
    xrange_data=None,
    xrange_categories=None,
):
    """
    Generate Highcharts configuration JSON for frontend rendering.

    Args:
        chart_type: Type of chart (bar, column, line, pie, area, spline, areaspline, heatmap, xrange)
        title: Chart title
        x_axis_data: List of category labels for x-axis (or heatmap column labels)
        series_data: List of series objects with 'name' and 'data' keys (ignored for heatmap/xrange)
        y_axis_title: Optional y-axis label
        stacking: Optional 'normal' or 'percent' for bar/column (stacked charts)
        subtitle: Optional subtitle text below title
        heatmap_data: For heatmap: [[xIndex, yIndex, value], ...] where indices refer to x_axis_data, y_axis_data
        y_axis_data: For heatmap: row category labels (e.g. hours, days)
        xrange_data: For xrange: [{x: startMs, x2: endMs, name: "Event"}, ...] with Unix ms timestamps

    Returns:
        Dict with type='highcharts' and config for frontend to render

    Reference: https://api.highcharts.com/highcharts/
    """
    # Heatmap: events by day × hour, etc.
    if chart_type == "heatmap":
        return _build_heatmap_config(
            title, x_axis_data or [], y_axis_data or [], heatmap_data or [], subtitle
        )
    # X-range: event schedules / timeline
    if chart_type == "xrange":
        return _build_xrange_config(title, xrange_data or [], subtitle, xrange_categories)

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
        },
        "exporting": {
            "enabled": True,
            "buttons": {
                "contextButton": {
                    "menuItems": ["viewFullScreen", "printChart", "separator", "downloadPNG", "downloadJPEG", "downloadPDF", "downloadSVG"]
                }
            }
        },
        "noData": {
            "style": {"fontSize": "14px"},
            "position": {"align": "center", "verticalAlign": "middle"}
        },
        "responsive": {
            "rules": [
                {
                    "condition": {"maxWidth": 500},
                    "chartOptions": {
                        "legend": {"align": "center", "verticalAlign": "bottom"},
                        "chart": {"height": 300}
                    }
                }
            ]
        }
    }

    if subtitle:
        highcharts_config["subtitle"] = {"text": subtitle}
    
    # Chart-type specific plotOptions
    if chart_type in ["bar", "column"]:
        bar_opts = {
            "dataLabels": {"enabled": True},
            "borderRadius": 3
        }
        if stacking in ("normal", "percent"):
            bar_opts["stacking"] = stacking
        highcharts_config["plotOptions"][chart_type] = bar_opts
    elif chart_type in ["line", "spline"]:
        highcharts_config["plotOptions"][chart_type] = {
            "dataLabels": {"enabled": True},
            "marker": {"enabled": True}
        }
    elif chart_type in ["area", "areaspline"]:
        highcharts_config["plotOptions"][chart_type] = {
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


def _build_heatmap_config(title, x_categories, y_categories, heatmap_data, subtitle=None):
    """Build Highcharts config for heatmap. Data: [[xIndex, yIndex, value], ...]"""
    config = {
        "chart": {"type": "heatmap"},
        "title": {"text": title},
        "xAxis": {"categories": x_categories},
        "yAxis": {"categories": y_categories, "title": None},
        "colorAxis": {
            "min": 0,
            "minColor": "#FFFFFF",
            "maxColor": "#7cb5ec"
        },
        "series": [{
            "name": "Count",
            "borderWidth": 1,
            "data": heatmap_data,
            "dataLabels": {"enabled": True, "format": "{point.value}"}
        }],
        "tooltip": {
            "format": "<b>{point.x}</b><br/><b>{point.y}</b><br/>Count: {point.value}"
        },
        "legend": {"enabled": False},
        "credits": {"enabled": False},
        "exporting": {"enabled": True},
        "noData": {"style": {"fontSize": "14px"}, "position": {"align": "center", "verticalAlign": "middle"}},
        "responsive": {"rules": [{"condition": {"maxWidth": 500}, "chartOptions": {"chart": {"height": 300}}}]}
    }
    if subtitle:
        config["subtitle"] = {"text": subtitle}
    return {"type": "highcharts", "config": config}


def _build_xrange_config(title, xrange_data, subtitle=None, xrange_categories=None):
    """Build Highcharts config for x-range timeline. Data: [{x: startMs, x2: endMs, name: "Event", y?: rowIndex}, ...]"""
    # Ensure each point has y (row index); default 0
    data = []
    for pt in xrange_data:
        p = dict(pt)
        if "y" not in p:
            p["y"] = 0
        data.append(p)
    y_indices = sorted(set(p["y"] for p in data))
    categories = xrange_categories or [f"Row {i}" for i in y_indices] if y_indices else ["Events"]
    config = {
        "chart": {"type": "xrange"},
        "title": {"text": title},
        "xAxis": {"type": "datetime"},
        "yAxis": {"title": None, "categories": categories, "reversed": True},
        "series": [{
            "name": "Events",
            "data": data,
            "dataLabels": {"enabled": True, "format": "{point.name}"}
        }],
        "tooltip": {"format": "<b>{point.name}</b><br/>Start: {point.x:datetime}<br/>End: {point.x2:datetime}"},
        "legend": {"enabled": False},
        "credits": {"enabled": False},
        "exporting": {"enabled": True},
        "noData": {"style": {"fontSize": "14px"}, "position": {"align": "center", "verticalAlign": "middle"}},
        "responsive": {"rules": [{"condition": {"maxWidth": 500}, "chartOptions": {"chart": {"height": 300}}}]}
    }
    if subtitle:
        config["subtitle"] = {"text": subtitle}
    return {"type": "highcharts", "config": config}
