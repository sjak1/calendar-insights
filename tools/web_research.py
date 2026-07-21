"""
Web research for briefing preparation.

Read-only. Nothing here writes to BriefingIQ — findings come back with their
source URLs so the agent can show them to the user, who decides what (if
anything) goes onto the record via the confirmation-gated edit tools.

Provider-agnostic: Anthropic's server-side web_search tool is not available on
Amazon Bedrock (see shared platform availability), and this app runs Claude via
Bedrock, so search goes through a third-party API instead. Set:

    WEB_SEARCH_PROVIDER=tavily|brave|serper   (default: tavily)
    WEB_SEARCH_API_KEY=<key for that provider>

With no key configured the tools return a clear error rather than failing the
whole turn — the rest of the agent keeps working.
"""
import os
import time
from typing import Any, Dict, List, Optional

import requests

from logging_config import get_logger

logger = get_logger(__name__)

_TIMEOUT = 20
_CACHE: Dict[str, Any] = {}
_CACHE_TTL = 900  # 15 min — company facts don't move within a conversation
_MAX_SNIPPET = 400


def _provider() -> str:
    return (os.environ.get("WEB_SEARCH_PROVIDER") or "tavily").strip().lower()


def _api_key() -> str:
    return (os.environ.get("WEB_SEARCH_API_KEY") or "").strip()


def _not_configured() -> Dict[str, Any]:
    return {
        "error": (
            "Web search is not configured. Set WEB_SEARCH_API_KEY (and optionally "
            "WEB_SEARCH_PROVIDER=tavily|brave|serper). Tell the user web research is "
            "unavailable and answer from the briefing data you already have."
        )
    }


def _trim(text: Optional[str]) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:_MAX_SNIPPET] + ("…" if len(text) > _MAX_SNIPPET else "")


def _tavily(query: str, max_results: int, key: str) -> List[Dict[str, str]]:
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": _trim(r.get("content"))}
        for r in resp.json().get("results", [])
    ]


def _brave(query: str, max_results: int, key: str) -> List[Dict[str, str]]:
    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": max_results},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    results = (resp.json().get("web") or {}).get("results", [])
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": _trim(r.get("description"))}
        for r in results
    ]


def _serper(query: str, max_results: int, key: str) -> List[Dict[str, str]]:
    resp = requests.post(
        "https://google.serper.dev/search",
        json={"q": query, "num": max_results},
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return [
        {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": _trim(r.get("snippet"))}
        for r in resp.json().get("organic", [])
    ]


_PROVIDERS = {"tavily": _tavily, "brave": _brave, "serper": _serper}


def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Run a web search. Returns {query, provider, results:[{title,url,snippet}]}.

    Every result carries its source URL — always show those to the user; a
    search snippet is a claim, not a verified fact.
    """
    key = _api_key()
    if not key:
        return _not_configured()

    provider = _provider()
    fetch = _PROVIDERS.get(provider)
    if fetch is None:
        return {
            "error": f"Unknown WEB_SEARCH_PROVIDER '{provider}'. Use one of: {', '.join(_PROVIDERS)}."
        }

    query = (query or "").strip()
    if not query:
        return {"error": "query is required."}
    max_results = max(1, min(int(max_results or 5), 10))

    cache_key = f"{provider}|{query}|{max_results}"
    cached = _CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        logger.debug(f"web search cache hit: {query!r}")
        return cached[1]

    logger.info(f"🌐 web search ({provider}): {query!r}")
    try:
        results = fetch(query, max_results, key)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        # Don't echo the response body — provider errors can contain the key.
        logger.warning(f"web search failed: HTTP {status}")
        hint = " Check WEB_SEARCH_API_KEY." if status in (401, 403) else ""
        return {"error": f"Web search failed (HTTP {status}).{hint}"}
    except requests.RequestException as exc:
        logger.warning(f"web search request error: {exc}")
        return {"error": f"Web search request failed: {exc}"}

    payload = {"query": query, "provider": provider, "results": results}
    _CACHE[cache_key] = (time.time(), payload)
    logger.info(f"✓ web search returned {len(results)} result(s)")
    return payload


def research_company(company_name: str, focus: Optional[str] = None) -> Dict[str, Any]:
    """
    Gather public background on a customer ahead of a briefing.

    Runs a small set of targeted searches (profile, recent news, strategic
    priorities) and returns the raw findings grouped by angle, each with its
    source URL. Deliberately does not summarise into a verdict — the agent
    presents the findings and the user decides what is accurate and relevant.
    """
    company_name = (company_name or "").strip()
    if not company_name:
        return {"error": "company_name is required."}
    if not _api_key():
        return _not_configured()

    angles = [
        ("profile", f"{company_name} company headquarters industry overview"),
        ("recent_news", f"{company_name} news announcement 2026"),
        ("priorities", f"{company_name} strategy priorities investment"),
    ]
    if focus:
        angles.append(("focus", f"{company_name} {focus}"))

    findings: Dict[str, Any] = {}
    errors = []
    for angle, query in angles:
        result = search_web(query, max_results=4)
        if "error" in result:
            errors.append({angle: result["error"]})
            continue
        findings[angle] = result["results"]

    if not findings:
        return {
            "error": "All research queries failed.",
            "details": errors,
            "company_name": company_name,
        }

    payload: Dict[str, Any] = {
        "company_name": company_name,
        "findings": findings,
        "guidance": (
            "These are unverified public web results. Show the user what you found "
            "with source links and let them confirm before anything is written to a "
            "briefing. If the company name is ambiguous (a common word, or several "
            "companies share it), ask which entity they mean before relying on this."
        ),
    }
    if errors:
        payload["partial_errors"] = errors
    logger.info(f"✓ research_company '{company_name}': {len(findings)} angle(s)")
    return payload
