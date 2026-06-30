"""Request-scoped access context (Phase 3 enforcement plumbing).

search()/count() run deep inside tool execution, far from handle_query where the
caller's role is resolved. Rather than thread an argument through every layer, we
stash the resolved AccessContext in a context variable at request entry and read
it at the OpenSearch chokepoint.

contextvars are per-thread / per-async-context, so each request sees its own value
even under FastAPI concurrency and the stream endpoint's worker thread (which runs
handle_query in-thread, so the value is set where it's needed).

When unset (offline scripts, tests, non-request callers) enforcement is skipped —
search() behaves exactly as before. Enforcement only kicks in once set_access()
has run for this request.
"""

import contextvars
from typing import Optional

_access_ctx: contextvars.ContextVar = contextvars.ContextVar("rbac_access_ctx", default=None)
_pinned_event_id: contextvars.ContextVar = contextvars.ContextVar("rbac_event_id", default=None)


def set_access(ctx, event_id: Optional[str] = None) -> None:
    """Set the access context (and any header-pinned event id) for this request."""
    _access_ctx.set(ctx)
    _pinned_event_id.set(event_id)


def get_access():
    """The AccessContext for this request, or None when enforcement should be skipped."""
    return _access_ctx.get()


def get_pinned_event_id() -> Optional[str]:
    """The event id from the request header, if the user is scoped to one event."""
    return _pinned_event_id.get()


def clear_access() -> None:
    _access_ctx.set(None)
    _pinned_event_id.set(None)
