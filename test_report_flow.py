#!/usr/bin/env python
"""
Test report flow: format_report with mock data, then generate_report with real DSL if OpenSearch is available.
"""
import json
from tools.report import format_report, build_report_rows, generate_report

def test_format_report():
    """Test formatter with mock rows (no OpenSearch)."""
    rows = [
        {"customer_name": "Acme", "event_name": "Q1 Review", "status": "Confirmed", "location_name": "NYC"},
        {"customer_name": "Globex", "event_name": "Kickoff", "status": "Draft", "location_name": "London"},
    ]
    columns = [
        {"binding": "customer_name", "header": "Customer"},
        {"binding": "event_name", "header": "Event"},
        {"binding": "status", "header": "Status"},
        {"binding": "location_name", "header": "Location"},
    ]
    out = format_report(rows, columns, title="Events", subtitle="Sample")
    assert out["type"] == "report"
    assert "reportUiConfig" in out and "reportData" in out
    assert len(out["reportUiConfig"]["columns"]) == 4
    assert len(out["reportData"]) == 2
    assert out["reportData"][0]["customer_name"] == "Acme"
    print("format_report: OK")

def test_generate_report():
    """Test full generate_report with a minimal DSL (hits OpenSearch if configured)."""
    dsl = {
        "query": {"match_all": {}},
        "size": 5,
        "_source": ["eventName", "eventId", "status.stateName", "eventData.VISIT_INFO.data.customerName", "location.data.locationName"],
    }
    columns = [
        {"binding": "event_name", "header": "Event"},
        {"binding": "customer_name", "header": "Customer"},
        {"binding": "status", "header": "Status"},
        {"binding": "location_name", "header": "Location"},
    ]
    out = generate_report(dsl, columns, title="Events table", subtitle="Test run")
    assert out["type"] == "report"
    assert "reportUiConfig" in out and "reportData" in out
    if out.get("error"):
        print("generate_report: OpenSearch not available:", out["error"])
        return
    print("generate_report: OK, rows =", len(out["reportData"]))
    if out["reportData"]:
        print("  first row keys:", list(out["reportData"][0].keys()))

if __name__ == "__main__":
    test_format_report()
    test_generate_report()
    print("Done.")
