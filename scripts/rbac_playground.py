"""RBAC filter playground — see how a role turns into an OpenSearch filter.

Run it:
    python scripts/rbac_playground.py                 # runs the built-in examples
    python scripts/rbac_playground.py surya@allianceit.com     # by email (hits Oracle)
    python scripts/rbac_playground.py --roles 10,1    # by role ids, no email needed

What it shows for each case:
    1. the raw Oracle row-rules for the role(s)          ← the BASIS
    2. the compiled OpenSearch filter (pretty JSON)      ← the RESULT
    3. (optional) live doc counts with vs without the filter

Tweak the EXAMPLES list at the bottom, or pass args, and watch the filter change.
Needs VPN/Oracle for role lookups; OpenSearch for the live counts (optional).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from access.resolver import AccessContext, resolve_access_context
from access.policy import _load_role_rules, compile_access_filter, is_unrestricted


def show(ctx: AccessContext, live: bool = False):
    print("=" * 72)
    print(f"USER: {ctx.email or '(no email)'}   roles={ctx.role_names or ctx.role_ids}")
    print(f"      resolved={ctx.resolved}  locations={len(ctx.location_guids)}")
    print("-" * 72)

    # 1. THE BASIS — the raw Oracle rules behind the filter
    print("① Oracle row-rules (M_EVENT_ROLE_DATA_ACCESS_MAP):")
    rules_by_role = _load_role_rules(ctx.role_ids)
    for rid, rules in rules_by_role.items():
        print(f"   role {rid}:")
        for r in rules:
            print(f"      {r.property} {r.operation} {r.value}   (combine={r.condition})")
        if not rules:
            print("      (no rules — global role or none in this table)")

    # 2. THE RESULT — the compiled OpenSearch filter
    print("\n② Compiled OpenSearch filter:")
    filt = compile_access_filter(ctx)
    print(json.dumps(filt, indent=2))

    print(f"\n   is_unrestricted (see-everything for activities)? {is_unrestricted(ctx)}")

    # 3. Optional live proof
    if live:
        try:
            from opensearch_client import search
            body_all = {"size": 0, "query": {"match_all": {}}}
            body_scoped = {"size": 0, "query": {"bool": {"filter": filt, "must": [{"match_all": {}}]}}}
            # use the RAW client path so we bypass enforcement double-wrapping
            from opensearch_client import _get_client, _index
            def cnt(b):
                return _get_client().search(index=_index("events"), body=b)["hits"]["total"]["value"]
            print(f"\n③ Live events count:  no filter = {cnt(body_all)}   with filter = {cnt(body_scoped)}")
        except Exception as e:
            print(f"\n③ (live count skipped: {e})")
    print()


# ---- edit these to experiment -------------------------------------------------
# Hand-build a context (no Oracle needed for the role part) by setting role_ids.
# Role ids:  1=Super User  2=Briefing Manager  3=Scheduler  4=Application User
#            5=Technical Mgr  9=Presenter  10=Requester  11=Super Admin
EXAMPLES = [
    AccessContext(email="me@example.com", user_id=1, role_ids=[10],
                  role_names=["Requester"], resolved=True),
    AccessContext(email="me@example.com", user_id=1, role_ids=[1],
                  role_names=["Super User"], resolved=True),
    AccessContext(email="me@example.com", user_id=1, role_ids=[10, 1],
                  role_names=["Requester", "Super User"], resolved=True),
    AccessContext(email=None, user_id=None, role_ids=[], role_names=[], resolved=False),  # unknown
]


def main():
    args = sys.argv[1:]
    if args and args[0] == "--roles":
        ids = [int(x) for x in args[1].split(",")]
        show(AccessContext(email="me@example.com", user_id=1, role_ids=ids,
                           role_names=[f"role{i}" for i in ids], resolved=True), live=True)
    elif args:
        # treat arg as an email → full Oracle resolution
        show(resolve_access_context(email=args[0]), live=True)
    else:
        for ctx in EXAMPLES:
            show(ctx, live=False)


if __name__ == "__main__":
    main()
