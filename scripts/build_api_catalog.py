"""
Build a compact, agent-friendly catalog of BriefingIQ read-only (GET) endpoints
from the public OpenAPI specs served by the Swagger UI at https://api.briefingiq.com.

Dev-time script (requires PyYAML; not a runtime dependency — the agent only
reads the generated JSON). Regenerate whenever the upstream specs change:

    python scripts/build_api_catalog.py            # fetch specs + write catalog
    python scripts/build_api_catalog.py --from-dir ./specs   # use local copies

Output: data/briefingiq_api_catalog.json — one entry per GET endpoint with
path, tag, summary and parameter list. Consumed by tools/api_catalog.py.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

SPEC_HOST = "https://api.briefingiq.com"
SPEC_FILES = [
    "biq-eiq-new-features.yaml",
    "biq-event.yaml",
    "biq-admin.yaml",
    "digital-signage-api.yaml",
]

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "data" / "briefingiq_api_catalog.json"

_MAX_DESC_CHARS = 220


def _clean_text(text):
    """Collapse whitespace and trim long descriptions to a single compact line."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _MAX_DESC_CHARS:
        text = text[: _MAX_DESC_CHARS - 1].rstrip() + "…"
    return text


def _endpoint_id(method, path):
    slug = re.sub(r"[{}]", "", path).strip("/").replace("/", "_")
    return f"{method.lower()}_{slug}"


def _extract_params(operation, path_item):
    """Merge path-level and operation-level parameters (operation wins on name)."""
    merged = {}
    for source in (path_item.get("parameters") or [], operation.get("parameters") or []):
        for param in source:
            if not isinstance(param, dict) or "name" not in param:
                continue
            merged[(param.get("in"), param["name"])] = param

    # Header params are omitted: auth + x-cloud-* headers are forwarded from the
    # incoming request by the runtime client, so the agent never supplies them.
    params = []
    for (location, name), param in merged.items():
        if location not in ("path", "query"):
            continue
        params.append(
            {
                "name": name,
                "in": location,
                "required": bool(param.get("required")),
                "description": _clean_text(param.get("description")),
            }
        )
    params.sort(key=lambda p: ({"path": 0, "query": 1}[p["in"]], p["name"]))
    return params


def build_catalog(spec_texts):
    """spec_texts: dict of spec filename -> raw YAML text."""
    endpoints = []
    for spec_name, raw in spec_texts.items():
        spec = yaml.safe_load(raw)
        for path, path_item in (spec.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            operation = path_item.get("get")
            if not isinstance(operation, dict):
                continue  # read-only catalog: GET endpoints only
            tags = operation.get("tags") or []
            summary = _clean_text(
                operation.get("summary") or operation.get("description")
            )
            endpoints.append(
                {
                    "id": _endpoint_id("get", path),
                    "method": "GET",
                    "path": path,
                    "spec": spec_name,
                    "tag": _clean_text(tags[0]) if tags else "",
                    "summary": summary,
                    "params": _extract_params(operation, path_item),
                }
            )

    # De-duplicate across specs (same path may appear in several files); first spec wins.
    seen = {}
    for endpoint in endpoints:
        seen.setdefault(endpoint["id"], endpoint)
    catalog = sorted(seen.values(), key=lambda e: e["path"])
    return catalog


def fetch_spec_texts():
    import requests

    texts = {}
    for name in SPEC_FILES:
        url = f"{SPEC_HOST}/{name}"
        print(f"Fetching {url} ...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        texts[name] = response.text
    return texts


def load_spec_texts(directory):
    texts = {}
    for name in SPEC_FILES:
        path = Path(directory) / name
        if not path.exists():
            print(f"warning: {path} missing, skipping", file=sys.stderr)
            continue
        texts[name] = path.read_text()
    return texts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-dir",
        help="Read spec YAMLs from a local directory instead of fetching them.",
    )
    args = parser.parse_args()

    spec_texts = load_spec_texts(args.from_dir) if args.from_dir else fetch_spec_texts()
    if not spec_texts:
        sys.exit("No specs loaded.")

    catalog = build_catalog(spec_texts)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"endpoints": catalog}, indent=1) + "\n")
    print(f"Wrote {len(catalog)} GET endpoints to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
