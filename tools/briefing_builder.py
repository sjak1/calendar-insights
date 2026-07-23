"""
Briefing builder — the write half of the agentic briefing flow.

In this tenant a briefing IS an event (category "Customer Briefing Request",
CBR-* numbers) created through the forms engine — not a "meeting" (that
subsystem belongs to the tradeshow module). See docs/BRIEFINGIQ_API_GUIDE.md.

Flow (strictly ordered):
  1. The agent interviews the user and gathers data (catalog / OpenSearch tools).
  2. draft_briefing(...)  → validates + assembles a complete draft, returns a
     draft_id and a human-readable summary. NO writes happen here.
  3. The agent shows the summary; the user must explicitly confirm.
  4. push_briefing(draft_id, ...) → executes the verified write chain:
        a. POST /forms/{requestFormId}/data       → creates the CBR event (requestId)
        b. PUT  .../data/{requestId}/actions/SUBMIT?sendNotification=false
        c. push_agenda_to_app(...)                → agenda sessions (optional)
     Partial failures are reported per step; completed steps are never rolled back.

The moduleId/journeyId/pageId/formId are discovered at runtime (they differ per
tenant): category with identifier REQUEST_TYPE → module with moduleType
REQUEST_CREATION → its journey/page/form config. Verified live 2026-07-17
(create → CBR-20260724-108 → SUBMIT → CANCEL, all 200).

Drafts live in process memory with a TTL — a draft_id from an old session
cannot be replayed after expiry.
"""
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from logging_config import get_logger
from tools.briefingiq_writer import BASE_URL, _hget, _make_headers, push_agenda_to_app

logger = get_logger(__name__)

_DRAFTS: Dict[str, Dict[str, Any]] = {}
_DRAFT_TTL = 3600  # 1 hour — long enough for a review conversation

_REQUEST_CTX_CACHE: Dict[Any, Dict[str, Any]] = {}
_REQUEST_CTX_TTL = 3600

_ALIAS_CACHE: Dict[str, Dict[str, Any]] = {}
_ALIAS_TTL = 3600


def _now() -> float:
    return time.time()


def _prune_drafts() -> None:
    expired = [k for k, v in _DRAFTS.items() if _now() - v["created"] > _DRAFT_TTL]
    for k in expired:
        del _DRAFTS[k]


def _tz_name(schedule_headers: Optional[Dict]) -> str:
    return (
        _hget(schedule_headers or {}, "x-cloud-requested-timezone", "x-cloud-context-timezone")
        or "America/Los_Angeles"
    )


def _to_ms(date_str: str, time_str: str, tz_name: str) -> int:
    """'2026-07-20' + '10:00' (24h) → epoch ms in the request timezone."""
    dt = datetime.strptime(f"{date_str}T{time_str}", "%Y-%m-%dT%H:%M")
    try:
        from zoneinfo import ZoneInfo

        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    except ImportError:
        pass
    return int(dt.timestamp() * 1000)


def _embedded_items(payload: Dict) -> List[Dict]:
    for value in (payload.get("_embedded") or {}).values():
        if isinstance(value, list):
            return value
    return []


def _fetch_event_locations(headers: Dict[str, str], event_id: str) -> List[Dict]:
    """Rooms attached to an event — used by briefing_editor to resolve room names."""
    url = f"{BASE_URL}/events/{event_id}/locations"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"event locations fetch failed: HTTP {resp.status_code}")
            return []
        data = resp.json()
        return _embedded_items(data) or (data if isinstance(data, list) else [])
    except requests.RequestException as exc:
        logger.warning(f"event locations fetch failed: {exc}")
        return []


def _location_name(loc: Dict) -> str:
    for key in ("locationName", "name", "displayName"):
        if loc.get(key):
            return str(loc[key])
    meta = loc.get("metaData") or {}
    return str(meta.get("searchDisplayText") or loc.get("uniqueId") or "")


def _resolve_room(headers: Dict, event_id: str, room_name: Optional[str]):
    """Returns (location_dict_or_None, available_names, note)."""
    locations = _fetch_event_locations(headers, event_id)
    names = [_location_name(l) for l in locations]
    if not room_name:
        return None, names, "No room requested."
    want = room_name.lower().strip()
    for loc in locations:
        name = _location_name(loc).lower()
        if want == name or want in name or name in want:
            return loc, names, None
    return None, names, f"Room '{room_name}' not found on this event."


def _fetch_field_aliases(headers: Dict[str, str], form_id: str) -> Dict[str, Any]:
    """
    Build the alias↔raw-attribute map for a form from its fieldmappings.

    Returns {"pairs": {name: (alias, attr)}, "multi": {names...}} where every
    alias and attribute name keys into the same (alias, attr) tuple.
    """
    cached = _ALIAS_CACHE.get(form_id)
    if cached and _now() - cached["ts"] < _ALIAS_TTL:
        return cached["map"]

    # Must be fetched WITHOUT x-cloud-eventid: with it, the server scopes the
    # lookup to the event and returns an empty page.
    lookup_headers = {k: v for k, v in headers.items() if k.lower() != "x-cloud-eventid"}
    resp = requests.get(f"{BASE_URL}/forms/{form_id}/fieldmappings", headers=lookup_headers, timeout=30)
    resp.raise_for_status()

    pairs: Dict[str, Tuple[str, str]] = {}
    multi: set = set()
    for mapping in _embedded_items(resp.json()):
        column = mapping.get("columnAttribute") or {}
        attr = column.get("attributeName")
        alias = mapping.get("aliasName") or attr
        if not attr:
            continue
        pairs[alias] = (alias, attr)
        pairs[attr] = (alias, attr)
        if mapping.get("multivalueField"):
            multi.update({alias, attr})

    alias_map = {"pairs": pairs, "multi": multi}
    _ALIAS_CACHE[form_id] = {"ts": _now(), "map": alias_map}
    # Log the form's real vocabulary: the create payload has been built from
    # inferred names, and every field we don't send stays blank on the record.
    logger.info(
        "form %s fieldmappings — %d field(s): %s",
        form_id,
        len({attr for _, attr in pairs.values()}),
        sorted({alias for alias, _ in pairs.values()}),
    )
    return alias_map


def _resolve_create_fields(
    headers: Dict[str, str], form_id: str, values: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Map logical create-request values onto the form's real attribute names.

    The UI reads /forms/{id}/fieldmappings before every write; we previously
    hardcoded textField1/textField2, which only holds if the tenant's mapping
    happens to match. Each logical field is tried against the form's aliases
    and attribute names (its alias label first, then the legacy raw column).

    Returns (data, unresolved_labels). Unresolved fields are reported to the
    caller rather than silently dropped.
    """
    try:
        alias_map = _fetch_field_aliases(headers, form_id)
        pairs, multi = alias_map["pairs"], alias_map["multi"]
    except Exception as exc:
        logger.warning(
            f"fieldmappings lookup failed for form {form_id} ({exc}); "
            "falling back to the hardcoded textField names."
        )
        pairs, multi = {}, set()

    data: Dict[str, Any] = {}
    unresolved: List[str] = []
    for label, candidates, value in values["fields"]:
        target = next((c for c in candidates if c in pairs), None)
        if target is None:
            # No mapping available (or lookup failed) — fall back to the raw
            # column name, which is what shipped before this resolution existed.
            fallback = candidates[-1]
            data[fallback] = value
            unresolved.append(label)
            continue
        alias, attr = pairs[target]
        for name in (alias, attr):
            data[name] = [value] if name in multi and not isinstance(value, list) else value

    data.update(values["literals"])
    if unresolved:
        logger.warning(
            "create-request fields not found in fieldmappings, wrote raw column names: %s",
            unresolved,
        )
    return data, unresolved


_VISIT_INFO_CTX_CACHE: Dict[Any, Dict[str, Any]] = {}
_VISIT_INFO_CTX_TTL = 3600


def _discover_visit_info_context(headers: Dict[str, str]) -> Optional[Dict[str, str]]:
    """
    Resolve the tenant's VISIT_INFO form wiring: {module_id, journey_id,
    page_id, form_id}.

    The create form holds only 13 intake fields; the objective and all the
    company/meeting detail live on a separate VISIT_INFO form. That form's
    record is NOT auto-provisioned — the UI creates it — so to fill it from
    the API we must create it ourselves, which needs the module/journey/page/
    form wrapper.

    Discovery mirrors the UI, verified live 2026-07-23:
      GET /admin/moduleaccess      → module (moduleType JOURNEY) named
                                     "Visit Information"
      GET /modules/{module}/configs → its single config's form/journey/page,
                                     confirmed by form.formType.uniqueId ==
                                     VISIT_INFO
    Each id is overridable via BRIEFINGIQ_VISIT_INFO_{MODULE,JOURNEY,PAGE,FORM}_ID.
    Cached per (tenant, category type) for an hour.
    """
    cache_key = (
        headers.get("x-cloud-customerid", ""),
        headers.get("x-cloud-categorytypeid", ""),
    )
    cached = _VISIT_INFO_CTX_CACHE.get(cache_key)
    if cached and _now() - cached["ts"] < _VISIT_INFO_CTX_TTL:
        return cached["ctx"]

    env = {
        "module_id": os.environ.get("BRIEFINGIQ_VISIT_INFO_MODULE_ID", "").strip(),
        "journey_id": os.environ.get("BRIEFINGIQ_VISIT_INFO_JOURNEY_ID", "").strip(),
        "page_id": os.environ.get("BRIEFINGIQ_VISIT_INFO_PAGE_ID", "").strip(),
        "form_id": os.environ.get("BRIEFINGIQ_VISIT_INFO_FORM_ID", "").strip(),
    }
    if all(env.values()):
        _VISIT_INFO_CTX_CACHE[cache_key] = {"ts": _now(), "ctx": env}
        return env

    try:
        resp = requests.get(f"{BASE_URL}/admin/moduleaccess", headers=headers, timeout=30)
        resp.raise_for_status()
        module_id = None
        for item in _embedded_items(resp.json()):
            module = item.get("module") or {}
            mtype = module.get("moduleType")
            mtype = mtype.get("uniqueId") if isinstance(mtype, dict) else mtype
            name = (module.get("name") or module.get("moduleName") or "").strip().lower()
            if mtype == "JOURNEY" and "visit information" in name:
                module_id = module.get("uniqueId")
                break
        if not module_id:
            logger.warning("visit-info discovery: no 'Visit Information' JOURNEY module")
            return None

        resp = requests.get(f"{BASE_URL}/modules/{module_id}/configs", headers=headers, timeout=30)
        resp.raise_for_status()
        configs = _embedded_items(resp.json())
        config = next(
            (
                c
                for c in configs
                if ((c.get("form") or {}).get("formType") or {}).get("uniqueId") == "VISIT_INFO"
            ),
            configs[0] if configs else None,
        )
        if not config:
            logger.warning("visit-info discovery: module has no config")
            return None
    except (requests.RequestException, ValueError) as exc:
        logger.warning(f"visit-info discovery failed: {exc}")
        return None

    ctx = {
        "module_id": module_id,
        "journey_id": (config.get("journey") or {}).get("uniqueId"),
        "page_id": (config.get("page") or {}).get("uniqueId"),
        "form_id": (config.get("form") or {}).get("uniqueId"),
    }
    ctx = {k: (env[k] or v) for k, v in ctx.items()}  # env wins per-field
    if not ctx["form_id"]:
        logger.warning("visit-info discovery: config missing form id")
        return None
    _VISIT_INFO_CTX_CACHE[cache_key] = {"ts": _now(), "ctx": ctx}
    logger.info(f"discovered visit-info context: {ctx}")
    return ctx


def _existing_visit_info_record(scoped: Dict[str, str], form_id: str) -> Optional[Dict[str, Any]]:
    """The event's existing VISIT_INFO record (full object), or None if not yet created."""
    try:
        resp = requests.get(f"{BASE_URL}/forms/{form_id}/data", headers=scoped, timeout=30)
        if resp.status_code != 200:
            return None
        records = (resp.json().get("_embedded") or {}).get("formData") or []
    except (requests.RequestException, ValueError):
        return None
    return records[0] if records else None


def _write_visit_info(
    headers: Dict[str, str], request_id: str, values: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Put the briefing's detail fields onto its VISIT_INFO record, creating that
    record if it does not exist yet (the normal case for an API-created
    briefing — the UI would otherwise create it on first open).

    Field names are resolved from the form's own fieldmappings and written
    under both alias and raw column (as the UI stores them). Unmapped fields
    are reported, not dropped. Values are plain strings/arrays; object-valued
    fields (briefingManager, host resources) are references and not set here.
    """
    values = {k: v for k, v in values.items() if v not in (None, "", [])}
    if not values:
        return {"step": "visit_info", "ok": True, "skipped": "nothing to write"}

    ctx = _discover_visit_info_context(headers)
    if not ctx:
        return {
            "step": "visit_info",
            "ok": False,
            "error": "Could not resolve the VISIT_INFO form; briefing details not stored.",
            "fields": sorted(values),
        }

    form_id = ctx["form_id"]
    scoped = {**headers, "x-cloud-eventid": request_id}

    try:
        alias_map = _fetch_field_aliases(scoped, form_id)
        pairs, multi = alias_map["pairs"], alias_map["multi"]
    except Exception as exc:
        return {"step": "visit_info", "ok": False, "error": f"fieldmappings lookup failed: {exc}"}

    existing = _existing_visit_info_record(scoped, form_id)
    data: Dict[str, Any] = dict(existing.get("data") or {}) if existing else {}

    written, unmapped = [], []
    for name, value in values.items():
        pair = pairs.get(name)
        if pair is None:
            unmapped.append(name)
            continue
        for key in pair:
            data[key] = [value] if key in multi and not isinstance(value, list) else value
        written.append(name)

    if not written:
        return {
            "step": "visit_info",
            "ok": False,
            "error": "None of the supplied fields exist on this tenant's VISIT_INFO form.",
            "unmapped_fields": unmapped,
        }

    wrapper = {
        "moduleTypeId": "JOURNEY",
        "moduleId": ctx["module_id"],
        "journeyId": ctx["journey_id"],
        "pageId": ctx["page_id"],
        "formId": form_id,
        "eventId": request_id,
        "formTypeId": "VISIT_INFO",
        "formIdentifier": "VISIT_INFO",
        "data": data,
    }

    try:
        if existing and existing.get("id"):
            url = f"{BASE_URL}/forms/{form_id}/data/{existing['id']}"
            logger.info(f"visit_info: PUT {url} fields={written} unmapped={unmapped}")
            resp = requests.put(url, headers=scoped, json={**wrapper, "id": existing["id"]}, timeout=30)
        else:
            url = f"{BASE_URL}/forms/{form_id}/data"
            logger.info(f"visit_info: POST {url} (create) fields={written} unmapped={unmapped}")
            resp = requests.post(url, headers=scoped, json=wrapper, timeout=30)
    except requests.RequestException as exc:
        return {"step": "visit_info", "ok": False, "error": str(exc)}

    if resp.status_code not in (200, 201):
        return {
            "step": "visit_info",
            "ok": False,
            "error": f"HTTP {resp.status_code}",
            "body": resp.text[:300],
        }

    result: Dict[str, Any] = {
        "step": "visit_info",
        "ok": True,
        "created": not (existing and existing.get("id")),
        "fields_written": written,
    }
    if unmapped:
        result["unmapped_fields"] = unmapped
    return result


def _config_form_name(config: Dict) -> str:
    """Best-effort human name for a module config's form (shape varies by tenant)."""
    form = config.get("form") or {}
    for key in ("name", "formName", "displayName", "title", "identifier"):
        value = form.get(key) or config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _select_request_config(configs: List[Dict]) -> Dict:
    """
    Pick the customer-briefing create form out of the module's configs.

    A REQUEST_CREATION module can expose several forms (Customer Briefing
    Request → CBR-*, Executive Dining → EDR-*, a generic request → CRT-*).
    The API does not guarantee an order, so indexing [0] silently creates the
    wrong record type — observed live: CBR-20260724-108 on 2026-07-17 vs
    CRT-20260720-012 on 2026-07-20 from identical code.

    Selection order:
      1. BRIEFINGIQ_REQUEST_FORM_ID env var (explicit per-tenant override)
      2. form name matching "customer briefing" / "briefing request"
      3. form name containing "briefing"
      4. configs[0], with a warning — preserves the previous behaviour
    """
    named = [(c, _config_form_name(c)) for c in configs]
    logger.info(
        "request-creation configs available: %s",
        [{"form_id": (c.get("form") or {}).get("uniqueId"), "name": n} for c, n in named],
    )

    override = os.environ.get("BRIEFINGIQ_REQUEST_FORM_ID", "").strip()
    if override:
        for config, name in named:
            if (config.get("form") or {}).get("uniqueId") == override:
                logger.info(f"request form selected by env override: {override} ({name})")
                return config
        logger.warning(f"BRIEFINGIQ_REQUEST_FORM_ID={override} not found in configs; ignoring.")

    for pattern in (r"customer\s*brief|brief\w*\s*request", r"brief"):
        for config, name in named:
            if name and re.search(pattern, name, re.I):
                logger.info(f"request form selected by name match: {name!r} (/{pattern}/)")
                return config

    fallback_name = named[0][1] or "<unnamed>"
    logger.warning(
        "No briefing-like request form found among %d config(s); falling back to the first "
        "(%r). The created record may be the wrong request type — set "
        "BRIEFINGIQ_REQUEST_FORM_ID to pin the correct form.",
        len(named),
        fallback_name,
    )
    return configs[0]


def _category_name(category: Dict) -> str:
    return (category.get("categoryName") or category.get("name") or "").strip()


def _location_category_id(headers: Dict[str, str], category_type: str) -> str:
    """
    The location (identifier LOCATION) the caller is working in.

    The UI passes its own x-cloud-categoryid straight through as the `parent`
    of the create-request category lookup, so honour the caller's context
    first. Only when the request carries no category do we fall back to the
    tenant's first LOCATION.
    """
    caller_category = (headers.get("x-cloud-categoryid") or "").strip()
    if caller_category:
        return caller_category

    resp = requests.get(
        f"{BASE_URL}/categorytypes/{category_type}/categories", headers=headers, timeout=30
    )
    resp.raise_for_status()
    locations = [c for c in _embedded_items(resp.json()) if c.get("identifier") == "LOCATION"]
    if not locations:
        raise RuntimeError("Request carried no x-cloud-categoryid and the tenant has no LOCATION.")
    logger.warning(
        "No x-cloud-categoryid on the request; defaulting to location %r.",
        _category_name(locations[0]),
    )
    return locations[0]["uniqueId"]


def _select_event_category(headers: Dict[str, str], category_type: str, location_id: str) -> Dict:
    """
    Resolve the create-request category for a location.

    Mirrors the UI: ?identifier=REQUEST_TYPE&parent=<location>&features=CREATE_EVENT.
    Every location has its own set of request types, and each is a distinct
    category with its own event-number series — Redwood Shores' customer
    briefing category yields CBR-*, Austin's yields CRT-*. Creating against
    another location's category (or against the location itself) produces a
    record the UI cannot open.

    "Non Customer Briefing Request" and "Virtual Customer Briefing Request" are
    siblings that both contain the target name, so the match is exact first.
    """
    resp = requests.get(
        f"{BASE_URL}/categorytypes/{category_type}/categories",
        headers=headers,
        params={"identifier": "REQUEST_TYPE", "parent": location_id, "features": "CREATE_EVENT"},
        timeout=30,
    )
    resp.raise_for_status()
    children = _embedded_items(resp.json())
    logger.info(
        "CREATE_EVENT categories under location %s: %s",
        location_id,
        [{"id": c.get("uniqueId"), "name": _category_name(c)} for c in children],
    )
    if not children:
        raise RuntimeError(
            f"No CREATE_EVENT request category under location {location_id}. The briefing would "
            "be created against a container category and be unopenable in the UI."
        )

    target = os.environ.get("BRIEFINGIQ_REQUEST_CATEGORY", "Customer Briefing Request").strip()
    chosen = next((c for c in children if _category_name(c).lower() == target.lower()), None)
    if chosen is None:
        # Exclude the Non-/Virtual- variants before falling back to a loose match.
        chosen = next(
            (
                c
                for c in children
                if re.search(r"customer\s+briefing", _category_name(c), re.I)
                and not re.match(r"non|virtual", _category_name(c), re.I)
            ),
            None,
        )
    if chosen is None:
        chosen = children[0]
        logger.warning(
            "No %r category under location %s; falling back to %r.",
            target,
            location_id,
            _category_name(chosen),
        )
    logger.info(f"event category selected: {_category_name(chosen)!r} ({chosen.get('uniqueId')})")
    return chosen


def _discover_request_context(headers: Dict[str, str]) -> Dict[str, Any]:
    """
    Resolve the tenant's request-creation wiring at runtime:
      parent category (location, identifier REQUEST_TYPE)
      → child category with features=CREATE_EVENT
      → module (moduleType REQUEST_CREATION) → module config (journey/page/form).
    Cached per (tenant, category type, caller category) for an hour.
    """
    # Key on tenant, category type *and* the caller's category — the resolved
    # context is location-specific, so a coarser key would serve one user's
    # location to another for up to an hour.
    cache_key = (
        headers.get("x-cloud-customerid", ""),
        headers.get("x-cloud-categorytypeid", ""),
        headers.get("x-cloud-categoryid", ""),
    )
    cached = _REQUEST_CTX_CACHE.get(cache_key)
    if cached and _now() - cached["ts"] < _REQUEST_CTX_TTL:
        return cached["ctx"]

    category_type = headers.get("x-cloud-categorytypeid", "CATEGORY_TYPE_BRIEFINGS")
    location_id = _location_category_id(headers, category_type)
    request_category = _select_event_category(headers, category_type, location_id)

    req_headers = {**headers, "x-cloud-categoryid": request_category["uniqueId"]}

    resp = requests.get(f"{BASE_URL}/admin/moduleaccess", headers=req_headers, timeout=30)
    resp.raise_for_status()
    module_id = None
    for item in _embedded_items(resp.json()):
        module = item.get("module") or {}
        module_type = module.get("moduleType")
        type_id = module_type.get("uniqueId") if isinstance(module_type, dict) else module_type
        if type_id == "REQUEST_CREATION":
            module_id = module.get("uniqueId")
            break
    if not module_id:
        raise RuntimeError("No REQUEST_CREATION module accessible for this user.")

    resp = requests.get(f"{BASE_URL}/modules/{module_id}/configs", headers=req_headers, timeout=30)
    resp.raise_for_status()
    configs = _embedded_items(resp.json())
    if not configs:
        raise RuntimeError("Request-creation module has no journey/page/form config.")
    config = _select_request_config(configs)

    ctx = {
        "category_id": request_category["uniqueId"],
        "category_name": _category_name(request_category),
        "location_category_id": location_id,
        "module_id": module_id,
        "journey_id": (config.get("journey") or {}).get("uniqueId"),
        "page_id": (config.get("page") or {}).get("uniqueId"),
        "form_id": (config.get("form") or {}).get("uniqueId"),
        "form_name": _config_form_name(config),
    }
    if not ctx["form_id"]:
        raise RuntimeError("Module config is missing the create-request form id.")
    _REQUEST_CTX_CACHE[cache_key] = {"ts": _now(), "ctx": ctx}
    logger.info(f"discovered request context: {ctx}")
    return ctx


def draft_briefing(
    token: str,
    customer_name: str,
    briefing_date: str,
    start_time: str,
    end_time: str,
    opportunity_id: str = "",
    objective: Optional[str] = None,
    region: Optional[str] = None,
    company_website: Optional[str] = None,
    company_industry: Optional[str] = None,
    company_country: Optional[str] = None,
    visit_type: Optional[str] = None,
    visit_focus: Optional[str] = None,
    program: Optional[str] = None,
    pillars: Optional[List[str]] = None,
    sales_play: Optional[List[str]] = None,
    duration_days: int = 1,
    room_name: Optional[str] = None,
    presenter_emails: Optional[List[str]] = None,
    internal_attendees: Optional[List[Dict]] = None,
    external_attendees: Optional[List[Dict]] = None,
    agenda_sessions: Optional[List[Dict]] = None,
    schedule_headers: Optional[Dict] = None,
    event_id: str = "",  # unused in create flow; kept for call compatibility
) -> Dict[str, Any]:
    """
    Validate and assemble a briefing draft. NO writes. Returns draft_id + summary
    for user review. The create-request form requires customer name, opportunity
    id, date, start/end time, and duration (1-5 days).
    """
    _prune_drafts()

    missing = []
    if not customer_name:
        missing.append("customer_name")
    if not opportunity_id:
        missing.append("opportunity_id")
    for field, value in (("briefing_date", briefing_date), ("start_time", start_time), ("end_time", end_time)):
        if not value:
            missing.append(field)
    if missing:
        return {"success": False, "error": f"Missing required fields: {missing}"}
    if not 1 <= int(duration_days) <= 5:
        return {"success": False, "error": "duration_days must be between 1 and 5."}

    tz = _tz_name(schedule_headers)
    try:
        start_ms = _to_ms(briefing_date, start_time, tz)
        end_ms = _to_ms(briefing_date, end_time, tz)
    except ValueError as exc:
        return {"success": False, "error": f"Bad date/time format ({exc}). Use YYYY-MM-DD and HH:MM (24h)."}
    if end_ms <= start_ms:
        return {"success": False, "error": "end_time must be after start_time."}

    assumptions = []
    if objective and len(objective) > 200:
        assumptions.append(
            f"Objective is {len(objective)} characters and the form's field caps at 200 — "
            "it will be truncated. Shorten it if the tail matters."
        )
    if room_name:
        assumptions.append(
            f"Room preference '{room_name}' noted — room booking is a separate step after creation."
        )
    if internal_attendees or external_attendees:
        assumptions.append(
            "Attendees recorded on the draft; automated attendee push is not yet enabled."
        )

    briefing = {
        "customer_name": customer_name,
        "opportunity_id": opportunity_id,
        "objective": objective or "",
        "region": region or "",
        "company_website": company_website or "",
        "company_industry": company_industry or "",
        "company_country": company_country or "",
        "visit_type": visit_type or "",
        "visit_focus": visit_focus or "",
        "program": program or "",
        "pillars": pillars or [],
        "sales_play": sales_play or [],
        "briefing_date": briefing_date,
        "start_time": start_time,
        "end_time": end_time,
        "duration_days": int(duration_days),
        "timezone": tz,
        "room_name": room_name,
        "presenter_emails": presenter_emails or [],
        "internal_attendees": internal_attendees or [],
        "external_attendees": external_attendees or [],
        "agenda_sessions": agenda_sessions or [],
    }

    draft_id = uuid.uuid4().hex[:12]
    _DRAFTS[draft_id] = {"created": _now(), "briefing": briefing, "pushed": False}

    lines = [
        f"**Customer:** {customer_name}",
        f"**Opportunity:** {opportunity_id}",
        f"**Objective:** {objective or '—'}",
        f"**Region:** {region or '—'}",
        f"**Visit Type:** {visit_type or '—'}",
        f"**Date:** {briefing_date}  {start_time}–{end_time} ({tz}), {duration_days} day(s)",
        f"**Room preference:** {room_name or '—'}",
        f"**Presenters:** {', '.join(presenter_emails) if presenter_emails else '—'}",
        f"**Agenda sessions:** {len(agenda_sessions or [])}",
    ]

    return {
        "success": True,
        "draft_id": draft_id,
        "summary_markdown": "\n".join(lines),
        "briefing": briefing,
        "assumptions": assumptions,
        "next_step": (
            "Show this summary to the user. Only call push_briefing after they explicitly confirm."
        ),
    }


def push_briefing(
    draft_id: str,
    token: str,
    schedule_headers: Optional[Dict] = None,
    submit: bool = True,
) -> Dict[str, Any]:
    """
    Execute the writes for a confirmed draft. Ordered, partial-failure tolerant:
    create request (forms engine) → SUBMIT state action → agenda sessions.
    """
    _prune_drafts()
    entry = _DRAFTS.get(draft_id)
    if entry is None:
        return {"success": False, "error": f"Draft '{draft_id}' not found or expired. Re-run draft_briefing."}
    if entry["pushed"]:
        return {"success": False, "error": f"Draft '{draft_id}' was already pushed — refusing to push twice."}

    b = entry["briefing"]
    headers = _make_headers(token, None, schedule_headers)
    steps: List[Dict[str, Any]] = []

    # ── Step 0: discover the tenant's request-creation wiring ─────────────
    try:
        ctx = _discover_request_context(headers)
    except Exception as exc:
        return {"success": False, "steps": [{"step": "discover_context", "ok": False, "error": str(exc)}]}
    headers["x-cloud-categoryid"] = ctx["category_id"]

    # ── Step 1: create the briefing request via the forms engine ──────────
    form_id = ctx["form_id"]
    # Resolve field names from the form's own fieldmappings — the tenant's
    # customer/opportunity columns are not guaranteed to be textField1/2.
    # NB: textField3 is "Secondary Opportunity ID" (multi-value) per the form's
    # fieldmappings — NOT a free-text field.
    data, unresolved = _resolve_create_fields(
        headers,
        form_id,
        {
            "fields": [
                ("customer_name", ("Customer Name", "customerName", "textField1"), b["customer_name"]),
                (
                    "opportunity_id",
                    ("Primary Opportunity ID", "opportunityId", "textField2"),
                    b["opportunity_id"],
                ),
            ]
            # The create form maps 13 intake fields; region is one of them and
            # is a plain string ("JAPAC"). The objective is NOT on this form —
            # it belongs to VISIT_INFO and is written in step 1c below.
            + (
                [("region", ("region", "Company Region"), b["region"])]
                if b.get("region")
                else []
            ),
            "literals": {
                "duration": b["duration_days"],
                "startDate": {"isoDate": b["briefing_date"]},
                # The UI posts T00:00:00 for both times — its create form asks
                # only for a date and a duration in days. We keep the user's
                # real times: the API accepts them, and dropping them would
                # silently discard what the user asked for.
                "startTime": {"isoDate": f"{b['briefing_date']}T{b['start_time']}:00"},
                "endTime": {"isoDate": f"{b['briefing_date']}T{b['end_time']}:00"},
                # Secondary Opportunity ID — multivalue; the UI always sends it,
                # empty when unused.
                "textField3": [],
            },
        },
    )
    payload = {
        "moduleId": ctx["module_id"],
        "formId": form_id,
        "journeyId": ctx["journey_id"],
        "pageId": ctx["page_id"],
        "data": data,
    }

    url = f"{BASE_URL}/forms/{form_id}/data"
    logger.info(f"push_briefing {draft_id}: POST {url}")
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        return {"success": False, "steps": [{"step": "create_request", "ok": False, "error": str(exc)}]}

    body = {}
    if resp.status_code == 200 and resp.text.strip():
        try:
            body = resp.json()
        except ValueError:
            pass
    request_id = body.get("id")
    if not request_id:
        return {
            "success": False,
            "steps": [{
                "step": "create_request", "ok": False,
                "error": f"HTTP {resp.status_code}, no request id returned — briefing NOT created.",
                "body": resp.text[:500],
            }],
        }
    create_step = {"step": "create_request", "ok": True, "request_id": request_id}
    if unresolved:
        # Written under raw column names — surfaced so the agent can tell the
        # user these may not have landed on the form.
        create_step["unmapped_fields"] = unresolved
    steps.append(create_step)

    # Fetch the created event for its CBR number (nice for the user-facing summary).
    event_number = None
    try:
        ev = requests.get(f"{BASE_URL}/events/{request_id}", headers=headers, timeout=30)
        if ev.status_code == 200:
            event_number = ev.json().get("eventNumber")
    except requests.RequestException:
        pass

    request_headers = {**headers, "x-cloud-eventid": request_id}

    # ── Step 1c: briefing details onto VISIT_INFO ─────────────────────────
    # Runs before SUBMIT so the record is complete when it reaches the EBC
    # team. A failure here is reported but does not fail the push — the
    # briefing exists and the detail can be filled in afterwards.
    detail_values = {
        "meetingObjective": (b.get("objective") or "")[:200],
        "companyWebsite": b.get("company_website"),
        "customerIndustry": b.get("company_industry"),
        "country": b.get("company_country"),
        # Controlled-vocabulary fields — the agent supplies values it took from
        # list_briefing_field_values, so they resolve in the UI. Arrays pass
        # through as-is for the multivalue fields (pillars, salesPlay).
        "visitType": b.get("visit_type"),
        "visitFocus": b.get("visit_focus"),
        "program": b.get("program"),
        "pillars": b.get("pillars"),
        "salesPlay": b.get("sales_play"),
    }
    if any(v for v in detail_values.values()):
        steps.append(_write_visit_info(headers, request_id, detail_values))

    # ── Step 2: SUBMIT state action (no notifications) ────────────────────
    if submit:
        action_url = f"{BASE_URL}/forms/{form_id}/data/{request_id}/actions/SUBMIT"
        try:
            a_resp = requests.put(
                action_url, headers=request_headers,
                params={"sendNotification": "false"}, json={}, timeout=30,
            )
            ok = a_resp.status_code in (200, 204)
            step: Dict[str, Any] = {"step": "submit", "ok": ok}
            if not ok:
                step["error"] = f"HTTP {a_resp.status_code}"
                step["body"] = a_resp.text[:300]
            steps.append(step)
        except requests.RequestException as exc:
            steps.append({"step": "submit", "ok": False, "error": str(exc)})

    # ── Step 3: agenda sessions (optional, reuses the proven agenda push) ─
    if b["agenda_sessions"]:
        agenda_result = push_agenda_to_app(
            event_id=request_id,
            event_date=b["briefing_date"],
            sessions=b["agenda_sessions"],
            token=token,
            presenter_emails=b["presenter_emails"] or None,
            resource_id=None,
            schedule_headers=schedule_headers,
        )
        steps.append({"step": "push_agenda", "ok": bool(agenda_result.get("success")), "detail": agenda_result})

    if b["internal_attendees"] or b["external_attendees"]:
        steps.append({
            "step": "attendees", "ok": True, "skipped": True,
            "note": "Attendee push not yet automated — add them in the app.",
        })

    entry["pushed"] = True
    failed = [s["step"] for s in steps if not s["ok"]]
    return {
        "success": not failed,
        "request_id": request_id,
        "event_number": event_number,
        "steps": steps,
        "failed_steps": failed,
    }
