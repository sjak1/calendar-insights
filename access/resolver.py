"""Resolve a caller's role + data scope from the briefing app's Oracle tables.

Resolution chain (see docs/RBAC_ACCESS_MODEL_GUIDE.md):

    email (header)        -> M_USER.USER_NAME -> M_USER.ID  (user_id)
    (user_id, category)   -> M_USER_ROLE      -> role_id(s)  -> BI_ROLE.NAME
    user_id               -> BI_LOCATION_USER -> location_id(s, numeric)
    location_id (numeric) -> M_LOCATION        -> UNIQUE_ID (GUID, == OpenSearch location.uniqueId)

A role is NOT global — it is scoped per category. The active category arrives in the
request header (x-cloud-categoryid). Oracle stores numeric category ids while OpenSearch
indexes GUIDs, so we bridge numeric -> GUID via M_CATEGORY / M_LOCATION.

Phase 1: this only RESOLVES and returns the context (callers log it). No enforcement yet.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import text

from database import engine
from logging_config import get_logger

logger = get_logger(__name__)

# Resolution is cached briefly: these tables change rarely and a single query may
# trigger several lookups. TTL keeps us from hammering Oracle per request.
_CACHE_TTL_SECONDS = 300
_cache: dict = {}
_cache_lock = threading.Lock()


@dataclass
class AccessContext:
    """Who the caller is and what data scope they have, resolved from Oracle.

    Phase 1 carries this alongside user_info; later phases compile it into an
    OpenSearch filter.
    """

    email: Optional[str] = None
    user_id: Optional[int] = None
    category_id: Optional[str] = None  # raw header value (numeric id or GUID)
    customer_id: Optional[str] = None  # tenant, from x-cloud-customerid
    role_ids: List[int] = field(default_factory=list)
    role_names: List[str] = field(default_factory=list)
    # OpenSearch-ready GUIDs the user may see (match location.uniqueId.keyword)
    location_guids: List[str] = field(default_factory=list)
    resolved: bool = False  # True only if we found a user + at least one role

    @property
    def primary_role(self) -> Optional[str]:
        return self.role_names[0] if self.role_names else None

    def summary(self) -> str:
        return (
            f"AccessContext(email={self.email}, user_id={self.user_id}, "
            f"roles={self.role_names or '∅'}, "
            f"locations={len(self.location_guids)}, "
            f"category={self.category_id}, resolved={self.resolved})"
        )


def _query_role_data(email: str, category_id: Optional[str]) -> dict:
    """Run the Oracle lookups. Returns a plain dict (cache-friendly)."""
    out = {
        "user_id": None,
        "role_ids": [],
        "role_names": [],
        "location_guids": [],
    }
    with engine.connect() as conn:
        # 1. email -> user_id  (USER_NAME holds the login email; IS_ACTIVE is padded CHAR)
        row = conn.execute(
            text(
                "SELECT id FROM M_USER "
                "WHERE LOWER(user_name) = LOWER(:email) AND TRIM(is_active) = '1'"
            ),
            {"email": email},
        ).fetchone()
        if not row:
            logger.info(f"[rbac] no active M_USER for email={email}")
            return out
        user_id = int(row[0])
        out["user_id"] = user_id

        # 2. (user, category) -> roles.  If the header category maps to a numeric
        #    M_CATEGORY id, scope to it; otherwise fall back to all of the user's roles.
        cat_numeric = _resolve_category_numeric(conn, category_id)
        if cat_numeric is not None:
            roles = conn.execute(
                text(
                    "SELECT DISTINCT mur.role_id, r.name "
                    "FROM M_USER_ROLE mur JOIN BI_ROLE r ON r.id = mur.role_id "
                    "WHERE mur.user_id = :uid AND TRIM(mur.is_active) = '1' "
                    "AND (mur.category_id = :cat OR mur.category_id IS NULL)"
                ),
                {"uid": user_id, "cat": cat_numeric},
            ).fetchall()
        else:
            roles = conn.execute(
                text(
                    "SELECT DISTINCT mur.role_id, r.name "
                    "FROM M_USER_ROLE mur JOIN BI_ROLE r ON r.id = mur.role_id "
                    "WHERE mur.user_id = :uid AND TRIM(mur.is_active) = '1'"
                ),
                {"uid": user_id},
            ).fetchall()
        out["role_ids"] = [int(r[0]) for r in roles]
        out["role_names"] = [r[1] for r in roles]

        # 3. user -> allowed locations (numeric) -> GUIDs (match OpenSearch uniqueId)
        guids = conn.execute(
            text(
                "SELECT DISTINCT ml.unique_id "
                "FROM BI_LOCATION_USER lu JOIN M_LOCATION ml ON ml.id = lu.location_id "
                "WHERE lu.user_id = :uid AND TRIM(lu.is_active) = '1'"
            ),
            {"uid": user_id},
        ).fetchall()
        out["location_guids"] = [g[0] for g in guids if g[0]]

    return out


def _resolve_category_numeric(conn, category_id: Optional[str]) -> Optional[int]:
    """The header may carry a numeric category id or a GUID. Normalise to the
    numeric M_CATEGORY.ID used by M_USER_ROLE. Returns None if unresolvable."""
    if not category_id:
        return None
    cid = str(category_id).strip()
    if cid.isdigit():
        return int(cid)
    # GUID -> numeric id
    row = conn.execute(
        text("SELECT id FROM M_CATEGORY WHERE unique_id = :g"), {"g": cid}
    ).fetchone()
    return int(row[0]) if row else None


def resolve_access_context(
    email: Optional[str],
    category_id: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> AccessContext:
    """Resolve the caller's role + data scope. Cached for a short TTL.

    Never raises: on any error or missing data it returns an unresolved context
    (resolved=False) so callers can decide the fail-closed policy in a later phase.
    """
    ctx = AccessContext(email=email, category_id=category_id, customer_id=customer_id)
    if not email:
        logger.info("[rbac] no email in request; cannot resolve role")
        return ctx

    key = (email.lower(), str(category_id))
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL_SECONDS:
            data = hit[1]
        else:
            data = None

    if data is None:
        try:
            data = _query_role_data(email, category_id)
        except Exception as e:
            logger.warning(f"[rbac] role resolution failed for {email}: {e}")
            return ctx
        with _cache_lock:
            _cache[key] = (now, data)

    ctx.user_id = data["user_id"]
    ctx.role_ids = data["role_ids"]
    ctx.role_names = data["role_names"]
    ctx.location_guids = data["location_guids"]
    ctx.resolved = bool(data["user_id"] and data["role_ids"])
    return ctx
