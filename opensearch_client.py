"""
Thin OpenSearch client — MCP-style wrappers.
Env: OPENSEARCH_URL, OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD,
OPENSEARCH_VERIFY_CERTS, OPENSEARCH_TIMEOUT_SECONDS, OPENSEARCH_DEFAULT_INDICES.
"""

import json
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv()

_client: Any = None
_BANNED = frozenset({"script", "script_fields", "scripted_metric", "runtime_mappings"})
_MAX_SIZE = 50


def validate_json_string(value: str) -> None:
    """Validate that a string is valid JSON.

    Args:
        value: The string to validate as JSON.

    Raises:
        ValueError: If the string is not valid JSON.
    """
    try:
        json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"query is not valid JSON: {e.msg} (line {e.lineno}, col {e.colno})"
        ) from e


def normalize_scientific_notation(body: Any) -> Any:
    """Normalize scientific-notation floats in a request body.

    Args:
        body: The request body (dict, list, or JSON string).

    Returns:
        The normalized Python structure with floats converted to standard notation.
    """
    if isinstance(body, str):
        if not body:
            return body
        if body[0] in ("{", "["):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                return body
        else:
            return body

    if isinstance(body, dict):
        return {k: normalize_scientific_notation(v) for k, v in body.items()}
    elif isinstance(body, list):
        return [normalize_scientific_notation(item) for item in body]
    elif isinstance(body, float):
        if body == int(body):
            return int(body)
        return body
    return body


def normalize_query_structure(query: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize query structure to fix common malformed DSL patterns.

    Fixes:
    - Nested bool inside filter array (invalid OpenSearch DSL)

    Args:
        query: The query dict to normalize.

    Returns:
        The normalized query dict.
    """
    if not isinstance(query, dict):
        return query

    def fix_filter_item(item):
        if isinstance(item, dict) and "bool" in item:
            inner = item["bool"]
            if isinstance(inner, dict):
                fixed = {}
                for k, v in inner.items():
                    if k in ("must", "must_not", "should", "filter"):
                        if isinstance(v, list):
                            fixed[k] = [fix_filter_item(i) for i in v]
                        else:
                            fixed[k] = v
                    else:
                        fixed[k] = v
                return fixed
        return item

    if "query" in query:
        q = query["query"]
        if isinstance(q, dict):
            if "bool" in q:
                b = q["bool"]
                if isinstance(b, dict):
                    for key in ("must", "must_not", "should", "filter"):
                        if key in b and isinstance(b[key], list):
                            b[key] = [fix_filter_item(i) for i in b[key]]
            elif "filter" in q:
                f = q["filter"]
                if isinstance(f, list):
                    query["query"]["filter"] = [fix_filter_item(i) for i in f]

    return query


def _get_client():
    global _client
    if _client is not None:
        return _client
    url = os.getenv("OPENSEARCH_URL", "").strip()
    if not url:
        raise ValueError("OPENSEARCH_URL required")
    from opensearchpy import OpenSearch

    host = url.replace("https://", "").replace("http://", "").rstrip("/")
    use_ssl = url.startswith("https://")
    username = os.getenv("OPENSEARCH_USERNAME", "").strip()
    password = os.getenv("OPENSEARCH_PASSWORD", "").strip()
    _client = OpenSearch(
        hosts=[{"host": host, "port": 443 if use_ssl else 80}],
        http_auth=(username, password) if username else None,
        use_ssl=use_ssl,
        verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower()
        in ("true", "1", "yes"),
        timeout=int(os.getenv("OPENSEARCH_TIMEOUT_SECONDS", "120")),
    )
    return _client


def _index(index: Optional[str]) -> str:
    return (
        (index or "").strip()
        or os.getenv("OPENSEARCH_DEFAULT_INDICES", "").strip()
        or "*,-.*"
    )


def _check_banned(obj: Any, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in _BANNED:
                raise ValueError(f"Forbidden '{k}' at {path or 'root'}")
            _check_banned(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _check_banned(item, f"{path}[{i}]")


def search(
    index: Optional[str], body: Dict[str, Any], size_cap: Optional[int] = _MAX_SIZE
) -> Dict[str, Any]:
    """Run search. Body passed through as-is. Size capped."""
    _check_banned(body)
    b = dict(body)

    if isinstance(b.get("query"), str):
        validate_json_string(b["query"])
        b["query"] = json.loads(b["query"])

    b = normalize_scientific_notation(b)
    b = normalize_query_structure(b)

    if "size" in b:
        b["size"] = min(int(b["size"]), size_cap or 9999)
    else:
        b.setdefault("size", 10)
    try:
        resp = _get_client().search(index=_index(index), body=b)
        total = resp.get("hits", {}).get("total", {})
        total_val = total.get("value", total) if isinstance(total, dict) else total
        hits = [
            {
                "index": h.get("_index"),
                "id": h.get("_id"),
                "score": round(h.get("_score") or 0, 2),
                "source": h.get("_source", {}),
            }
            for h in resp.get("hits", {}).get("hits", [])
        ]
        out: Dict[str, Any] = {"success": True, "total_hits": total_val, "hits": hits}
        if "aggregations" in resp:
            out["aggregations"] = resp["aggregations"]
        return out
    except Exception as e:
        return {"success": False, "error": str(e), "total_hits": 0, "hits": []}


def count(
    index: Optional[str], body: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Run count."""
    try:
        resp = _get_client().count(index=_index(index), body=body or {})
        return {"success": True, "count": resp.get("count", 0)}
    except Exception as e:
        return {"success": False, "error": str(e), "count": 0}


def list_indices(
    index: Optional[str] = None, include_detail: bool = True
) -> Dict[str, Any]:
    """List indices. index: pattern (e.g. events* or empty for all). include_detail: full metadata vs names only."""
    try:
        params = {"format": "json"}
        if index and index.strip():
            params["index"] = index.strip()
        resp = _get_client().transport.perform_request(
            method="GET", url="/_cat/indices", params=params
        )
        if not include_detail:
            names = [r.get("index", "") for r in (resp or []) if isinstance(r, dict)]
            return {"success": True, "indices": names}
        return {"success": True, "indices": resp or []}
    except Exception as e:
        return {"success": False, "error": str(e), "indices": []}


def get_index_mapping(index: str) -> Dict[str, Any]:
    """Get index mapping."""
    try:
        resp = _get_client().indices.get(index=(index or "").strip())
        return {"success": True, "index": (index or "").strip(), "mapping": resp}
    except Exception as e:
        return {"success": False, "error": str(e)}


def generic_api(
    path: str, method: str = "GET", body: Any = None, params: Optional[Dict] = None
) -> Dict[str, Any]:
    """Call any OpenSearch API."""
    try:
        resp = _get_client().transport.perform_request(
            method=method.upper(), url=path, body=body, params=params
        )
        return {
            "success": True,
            "path": path,
            "method": method.upper(),
            "response": resp,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_raw_dsl(
    dsl_body: Dict[str, Any],
    index: Optional[str] = None,
    size_cap: Optional[int] = _MAX_SIZE,
    **_kwargs,
) -> Dict[str, Any]:
    """Backward-compat: execute raw DSL (no date normalization)."""
    return search(index=index, body=dsl_body, size_cap=size_cap)


def get_suggested_presenters(
    topic: Optional[str] = None,
    industry: Optional[str] = None,
    customer_name: Optional[str] = None,
    event_id: Optional[str] = None,
    limit: int = 10,
    index: Optional[str] = None,
) -> Dict[str, Any]:
    """Suggest presenters from activity matches. Delegates to tools.presenter_suggest."""
    try:
        from tools.presenter_suggest import get_suggested_presenters as _impl

        return _impl(
            topic=topic,
            industry=industry,
            customer_name=customer_name,
            event_id=event_id,
            limit=limit,
            index=index,
        )
    except ImportError:
        return {
            "success": False,
            "error": "presenter_suggest module not available",
            "suggested_presenters": [],
        }
