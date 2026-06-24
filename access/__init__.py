"""Role-based access control for Calendar Insights.

Resolves the caller's role + data scope from the briefing app's Oracle tables, so
queries can later be filtered to only what the user is allowed to see.

Phase 1 (this module): resolution only — turn request headers into an AccessContext.
Enforcement (filter injection in opensearch_client.search) comes in a later phase.

See docs/RBAC_ACCESS_MODEL_GUIDE.md for the data model this is built on.
"""

from access.resolver import AccessContext, resolve_access_context
from access.policy import compile_access_filter

__all__ = ["AccessContext", "resolve_access_context", "compile_access_filter"]
