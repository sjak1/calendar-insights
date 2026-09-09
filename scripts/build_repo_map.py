#!/usr/bin/env python3
"""
Regenerate static/repo_map.html from the code itself.

The map that lived here before was hand-written, so it went stale the moment a
module moved — by the time anyone looked at it, it described a repo that no
longer existed. Everything structural in the output is now derived:

  modules       every first-party .py file, sized by line count
  dependencies  real import statements, resolved to first-party modules
  tools         the `tools` list in tools/definitions.py, as the model sees it
  dispatch      each `tool_name == "..."` branch in handlers.execute_tool,
                and the implementation it calls

What cannot be derived is why a module exists. Those sentences live in
docs/repo_map_notes.json and are merged in by name; the script reports which
modules are still missing one. Delete a module and its note goes unused, add
one and the map shows it immediately — but with no description until someone
writes it.

    python scripts/build_repo_map.py            # regenerate
    python scripts/build_repo_map.py --check    # CI: fail if out of date
"""

import argparse
import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "repo_map.html"
NOTES = ROOT / "docs" / "repo_map_notes.json"

# Directories that hold no first-party application code.
SKIP_DIRS = {
    "venv", "node_modules", ".git", "__pycache__", "build", "package",
    "slides", "access", "vishnu-corp-demo", "documents", "data", "docs",
    "static", "logs", "tests",
}

# Which band of the diagram a module belongs to. First match wins; anything
# unmatched lands in "support", which is the signal to add a rule here.
LAYER_RULES = [
    ("entry",  lambda m: m in {"api", "lambda_handler"}),
    ("core",   lambda m: m in {"query_processor", "tools.handlers", "tools.definitions"}),
    ("llm",    lambda m: m in {"bedrock_llm"}),
    ("tools",  lambda m: m.startswith("tools.")),
    ("data",   lambda m: m in {"opensearch_client", "database", "session_manager"}),
    ("dev",    lambda m: m.startswith("scripts.") or m in {"bench_bedrock", "run_q"}),
]
LAYER_ORDER = ["entry", "core", "llm", "tools", "data", "support", "dev"]
LAYER_LABEL = {
    "entry": "Entry", "core": "Orchestration", "llm": "Model transport",
    "tools": "Tools", "data": "Data access", "support": "Support", "dev": "Dev only",
}

# Call names that say nothing about architecture.
NOISE_CALLS = {
    "info", "warning", "error", "debug", "exception", "get", "len", "str", "int",
    "dumps", "loads", "append", "isinstance", "sorted", "list", "dict", "set",
    "format", "join", "strip", "lower", "upper", "split", "range", "enumerate",
    "print", "type", "bool", "float", "items", "keys", "values", "replace", "any", "all",
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_modules() -> dict:
    """Map dotted module name -> path relative to the repo root."""
    mods = {}
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.name.startswith("test_"):   # loose test scripts, wherever they sit
            continue
        name = str(rel.with_suffix("")).replace("/", ".")
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        mods[name] = rel
    return mods


def layer_of(module: str) -> str:
    for name, matches in LAYER_RULES:
        if matches(module):
            return name
    return "support"


def resolve(dotted: str, modules: dict):
    """Longest prefix of a dotted name that is a first-party module."""
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in modules:
            return candidate
    return None


def imports_of(tree: ast.AST, modules: dict) -> set:
    """First-party modules this module imports, however it spells the import."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                hit = resolve(alias.name, modules)
                if hit:
                    found.add(hit)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            hit = resolve(node.module, modules)
            if hit:
                found.add(hit)
            # `from tools import handlers` names the module in the import list
            for alias in node.names:
                deeper = resolve(f"{node.module}.{alias.name}", modules)
                if deeper:
                    found.add(deeper)
    return found


def reexports(modules: dict) -> dict:
    """(package, symbol) -> the module that actually defines it.

    tools/__init__.py re-exports most of the tool functions, so handlers.py
    imports them from `tools` rather than from the module they live in. Left
    alone, every tool in the map would point at the package. One hop through
    the __init__ recovers the real home.
    """
    index = {}
    for pkg, rel in modules.items():
        if not rel.name == "__init__.py":
            continue
        tree = ast.parse((ROOT / rel).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                origin = resolve(node.module, modules)
                if origin and origin != pkg:
                    for alias in node.names:
                        index[(pkg, alias.asname or alias.name)] = origin
    return index


def symbol_sources(tree: ast.AST, modules: dict, exports: dict = None) -> dict:
    """Imported symbol -> the first-party module it came from.

    `from tools import briefing_editor` names a module, not a symbol, so the
    deeper resolution wins where it exists. Where the name really is a symbol
    re-exported by a package, `exports` carries it the last hop.
    """
    exports = exports or {}
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            origin = resolve(node.module, modules)
            if not origin:
                continue
            for alias in node.names:
                name = alias.asname or alias.name
                # resolve() falls back to the shortest matching prefix, so a
                # submodule only counts when it beats the package itself.
                deeper = resolve(f"{node.module}.{alias.name}", modules)
                if deeper and deeper != origin:
                    out[name] = deeper
                else:
                    out[name] = exports.get((origin, alias.name), origin)
    return out


# ---------------------------------------------------------------------------
# The tool layer
# ---------------------------------------------------------------------------

def tool_schemas() -> list:
    """The `tools` list from tools/definitions.py, exactly as the model sees it."""
    tree = ast.parse((ROOT / "tools" / "definitions.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "tools" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    return []


def _tool_names_in(test: ast.AST) -> list:
    """Tool names a branch answers to.

    Both spellings are in use: `tool_name == "x"` for a branch of its own, and
    `tool_name in ("x", "y")` where several tools share one body.
    """
    names = []
    for cmp in ast.walk(test):
        if not (isinstance(cmp, ast.Compare) and isinstance(cmp.left, ast.Name)
                and cmp.left.id == "tool_name" and cmp.ops):
            continue
        op, rhs = cmp.ops[0], cmp.comparators[0]
        if isinstance(op, ast.Eq) and isinstance(rhs, ast.Constant) and isinstance(rhs.value, str):
            names.append(rhs.value)
        elif isinstance(op, ast.In) and isinstance(rhs, (ast.List, ast.Tuple, ast.Set)):
            names += [e.value for e in rhs.elts
                      if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return names


def tool_dispatch(modules: dict) -> dict:
    """Tool name -> the functions its branch calls, and where they come from.

    Reads the if/elif chain in handlers.execute_tool. Calls made inside a
    nested tool_name branch are left to that branch.
    """
    src = (ROOT / "tools" / "handlers.py").read_text()
    tree = ast.parse(src)
    exports = reexports(modules)
    sources = symbol_sources(tree, modules, exports)
    handler_defs = {n.name for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    dispatcher = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "execute_tool"), None
    )
    if dispatcher is None:
        return {}

    out = {}
    for node in ast.walk(dispatcher):
        if not isinstance(node, ast.If):
            continue
        names = _tool_names_in(node.test)
        if not names:
            continue
        # A branch can import what it needs on the spot, so collect those too.
        local = dict(sources)
        for stmt in node.body:
            local.update(symbol_sources(stmt, modules, exports))

        calls = set()
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.If) and _tool_names_in(sub.test):
                    continue
                if not isinstance(sub, ast.Call):
                    continue
                fn = sub.func
                if isinstance(fn, ast.Name):
                    calls.add((None, fn.id))
                elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                    # briefing_editor.get_briefing() — the module is the qualifier
                    calls.add((fn.value.id, fn.attr))
                elif isinstance(fn, ast.Attribute):
                    calls.add((None, fn.attr))

        impls = []
        for qualifier, fn in sorted(calls, key=lambda c: c[1]):
            if fn in NOISE_CALLS:
                continue
            module = local.get(qualifier) if qualifier else local.get(fn)
            if module is None and qualifier is None and fn.startswith("_"):
                continue        # a private helper of handlers.py, not the impl
            if module is None and fn in handler_defs:
                module = "tools.handlers"
            if module is None:
                continue
            impls.append({"fn": fn, "module": module})

        seen, unique = set(), []
        for i in impls:
            key = (i["fn"], i["module"])
            if key not in seen:
                seen.add(key); unique.append(i)
        for name in names:
            out[name] = unique
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def summary_of(tree: ast.AST) -> str:
    """The module's own first paragraph of docstring, as its description.

    Deriving this beats maintaining it: a module that explains itself at the
    top of the file is already the single source of truth, and the note file
    only has to cover the ones that do not.
    """
    doc = (ast.get_docstring(tree) or "").strip()
    if not doc:
        return ""
    para = []
    for line in doc.splitlines():
        if not line.strip():
            break
        para.append(line.strip())
    return " ".join(para)


def build() -> dict:
    modules = discover_modules()
    notes = json.loads(NOTES.read_text()) if NOTES.exists() else {}

    nodes, edges = [], []
    for name, rel in sorted(modules.items()):
        source = (ROOT / rel).read_text()
        tree = ast.parse(source)
        defs = sum(
            1 for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        note = notes.get(name, {})
        nodes.append({
            "id": name,
            "file": str(rel),
            "layer": note.get("layer") or layer_of(name),
            "lines": len(source.splitlines()),
            "defs": defs,
            "desc": note.get("desc") or summary_of(tree),
            "from_note": bool(note.get("desc")),
        })
        for target in sorted(imports_of(tree, modules)):
            if target != name:
                edges.append({"from": name, "to": target})

    schemas = tool_schemas()
    dispatch = tool_dispatch(modules)
    catalog = []
    for schema in schemas:
        name = schema.get("name", "")
        catalog.append({
            "name": name,
            "desc": (schema.get("description") or "").strip(),
            "params": sorted(
                (schema.get("parameters") or {}).get("properties", {}).keys()
            ),
            "required": (schema.get("parameters") or {}).get("required", []),
            "impl": dispatch.get(name, []),
        })
    # Branches that answer to a name no schema declares (aliases, internal tools).
    undeclared = sorted(set(dispatch) - {s.get("name") for s in schemas})

    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        sha = "unknown"

    return {
        "nodes": nodes,
        "edges": edges,
        "tools": catalog,
        "undeclared": undeclared,
        "meta": {
            "sha": sha,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "modules": len(nodes),
            "deps": len(edges),
            "loc": sum(n["lines"] for n in nodes),
        },
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Repo Map — calendar-insights</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap">
<style>
:root{
  --ground:#0B0E14; --panel:#141922; --panel-2:#1B2230; --rule:#232B39;
  --ink:#C6CEDA; --ink-dim:#7C8798; --ink-bright:#EDF1F6;
  --entry:#5AC8FA; --core:#FFB454; --llm:#BC8CFF; --tools:#4ED8A0;
  --data:#F778BA; --support:#8B98AC; --dev:#5A6474;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
     font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 20px;
       padding:20px 24px 16px;border-bottom:1px solid var(--rule)}
h1{margin:0;font-size:17px;font-weight:600;letter-spacing:-.01em;color:var(--ink-bright)}
.meta{font-family:var(--mono);font-size:11.5px;color:var(--ink-dim);display:flex;gap:16px;flex-wrap:wrap}
.meta b{color:var(--ink);font-weight:500}
.warn{color:var(--core)}
nav{display:flex;gap:2px;padding:12px 24px 0;border-bottom:1px solid var(--rule)}
nav button{appearance:none;background:none;border:0;border-bottom:2px solid transparent;
  color:var(--ink-dim);font-family:var(--sans);font-size:13px;font-weight:500;
  padding:8px 14px;cursor:pointer}
nav button:hover{color:var(--ink)}
nav button[aria-selected="true"]{color:var(--ink-bright);border-bottom-color:var(--entry)}
nav button:focus-visible{outline:2px solid var(--entry);outline-offset:2px;border-radius:3px}
.bar{display:flex;gap:10px;align-items:center;padding:12px 24px;flex-wrap:wrap}
input[type=search]{background:var(--panel);border:1px solid var(--rule);border-radius:6px;
  color:var(--ink);font-family:var(--mono);font-size:12px;padding:6px 10px;min-width:240px}
input[type=search]:focus{outline:none;border-color:var(--entry)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-family:var(--mono);font-size:11px;color:var(--ink-dim)}
.legend i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}
main{padding:0 24px 40px}
.wrap{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:20px;align-items:start}
@media(max-width:1000px){.wrap{grid-template-columns:minmax(0,1fr)}}
.canvas{overflow-x:auto;border:1px solid var(--rule);border-radius:10px;background:var(--panel)}
svg{display:block}
.lane text{font-family:var(--mono);font-size:10px;fill:var(--ink-dim);
  letter-spacing:.09em;text-transform:uppercase}
.lane line{stroke:var(--rule)}
.edge{fill:none;stroke:var(--rule);stroke-width:1}
.edge.back{stroke-dasharray:3 3}
.edge.on{stroke:var(--entry);stroke-width:1.6}
.edge.out{stroke:var(--tools)}
.node rect{stroke-width:1;rx:5}
.node text{font-family:var(--mono);font-size:11px;dominant-baseline:middle}
.node .n{fill:var(--ink-bright)}
.node .l{fill:var(--ink-dim);font-size:9.5px}
.node{cursor:pointer}
.dim{opacity:.16}
aside{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:16px;
  position:sticky;top:16px}
aside h2{margin:0 0 2px;font-size:14px;font-family:var(--mono);color:var(--ink-bright);word-break:break-all}
aside .path{font-family:var(--mono);font-size:11px;color:var(--ink-dim);margin-bottom:12px;word-break:break-all}
aside p{margin:0 0 14px;font-size:12.5px;color:var(--ink)}
aside .none{color:var(--ink-dim);font-style:italic}
.stat{display:flex;gap:14px;font-family:var(--mono);font-size:11px;color:var(--ink-dim);
  padding-bottom:12px;margin-bottom:12px;border-bottom:1px solid var(--rule)}
.stat b{color:var(--ink);font-weight:500}
h3{margin:14px 0 6px;font-family:var(--mono);font-size:10px;letter-spacing:.09em;
   text-transform:uppercase;color:var(--ink-dim);font-weight:500}
ul{margin:0;padding:0;list-style:none}
li{font-family:var(--mono);font-size:11.5px;padding:2px 0;color:var(--ink)}
li button{appearance:none;background:none;border:0;padding:0;color:inherit;font:inherit;
  cursor:pointer;text-align:left}
li button:hover{color:var(--entry);text-decoration:underline}
table{width:100%;border-collapse:collapse}
.tools td{border-top:1px solid var(--rule);padding:11px 12px;vertical-align:top}
.tools tr:first-child td{border-top:0}
.tools .nm{font-family:var(--mono);font-size:12px;color:var(--tools);white-space:nowrap;font-weight:500}
.tools .ds{font-size:12.5px;color:var(--ink);max-width:640px}
.tools .im{font-family:var(--mono);font-size:11px;color:var(--ink-dim);white-space:nowrap}
.tools .im b{color:var(--core);font-weight:500}
.tools .pm{font-family:var(--mono);font-size:10.5px;color:var(--ink-dim);margin-top:5px}
.tools .pm span{color:var(--ink)}
.panelbox{border:1px solid var(--rule);border-radius:10px;background:var(--panel);overflow:hidden}
.hidden{display:none}
.note{font-size:12px;color:var(--ink-dim);padding:10px 24px 0}
</style>
</head>
<body>
<header>
  <h1>calendar-insights · repo map</h1>
  <div class="meta">
    <span><b id="m-mod"></b> modules</span>
    <span><b id="m-dep"></b> dependencies</span>
    <span><b id="m-tool"></b> tools</span>
    <span><b id="m-loc"></b> lines</span>
    <span>@<b id="m-sha"></b></span>
    <span id="m-gen"></span>
  </div>
</header>

<nav role="tablist">
  <button role="tab" id="tab-modules" aria-selected="true" aria-controls="view-modules">Modules</button>
  <button role="tab" id="tab-tools" aria-selected="false" aria-controls="view-tools">Tool catalog</button>
</nav>

<div class="bar">
  <input type="search" id="q" placeholder="filter by name…" autocomplete="off">
  <div class="legend" id="legend"></div>
</div>

<p class="note">Generated from the source by <code>scripts/build_repo_map.py</code> — do not edit by hand. Solid edges import forward; dashed edges point back up the stack.</p>

<main>
  <section id="view-modules" role="tabpanel" aria-labelledby="tab-modules">
    <div class="wrap">
      <div class="canvas"><svg id="graph"></svg></div>
      <aside id="detail"></aside>
    </div>
  </section>

  <section id="view-tools" role="tabpanel" aria-labelledby="tab-tools" class="hidden">
    <div class="panelbox"><table class="tools"><tbody id="toolrows"></tbody></table></div>
  </section>
</main>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const LAYERS = __LAYERS__;
const LABELS = __LABELS__;
const COLOR  = l => getComputedStyle(document.documentElement).getPropertyValue('--'+l).trim() || '#8B98AC';
/* Descriptions come from docstrings and tool schemas — text, not markup. */
const esc = s => String(s == null ? '' : s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

document.getElementById('m-mod').textContent  = D.meta.modules;
document.getElementById('m-dep').textContent  = D.meta.deps;
document.getElementById('m-tool').textContent = D.tools.length;
document.getElementById('m-loc').textContent  = D.meta.loc.toLocaleString();
document.getElementById('m-sha').textContent  = D.meta.sha;
document.getElementById('m-gen').textContent  = D.meta.generated;

document.getElementById('legend').innerHTML = LAYERS
  .filter(l => D.nodes.some(n => n.layer === l))
  .map(l => '<span><i style="background:'+COLOR(l)+'"></i>'+LABELS[l]+'</span>').join('');

/* ---- layout: one column per layer, nodes stacked ------------------------ */
const COLW = 214, NODEH = 34, GAP = 11, PADX = 26, PADY = 54;
const byLayer = {};
LAYERS.forEach(l => byLayer[l] = D.nodes.filter(n => n.layer === l));
const cols = LAYERS.filter(l => byLayer[l].length);
const tallest = Math.max(...cols.map(l => byLayer[l].length));
const W = PADX*2 + cols.length*COLW, H = PADY + tallest*(NODEH+GAP) + 30;

const pos = {};
cols.forEach((l, ci) => {
  const list = byLayer[l];
  const top = PADY + (tallest - list.length) * (NODEH+GAP) / 2;
  list.forEach((n, i) => {
    pos[n.id] = { x: PADX + ci*COLW, y: top + i*(NODEH+GAP), w: COLW-34, h: NODEH, layer: l, ci };
  });
});

const svg = document.getElementById('graph');
svg.setAttribute('viewBox', '0 0 '+W+' '+H);
svg.setAttribute('width', W); svg.setAttribute('height', H);
const NS = 'http://www.w3.org/2000/svg';
const el = (t, a) => { const e = document.createElementNS(NS, t);
  for (const k in a) e.setAttribute(k, a[k]); return e; };

/* lane headers */
cols.forEach((l, ci) => {
  const g = el('g', {class:'lane'});
  const t = el('text', {x: PADX + ci*COLW, y: 24});
  t.textContent = LABELS[l];
  g.appendChild(t);
  g.appendChild(el('line', {x1: PADX + ci*COLW, y1: 34, x2: PADX + ci*COLW + COLW-34, y2: 34}));
  svg.appendChild(g);
});

/* edges behind nodes */
const edgeEls = [];
const gEdges = el('g', {}); svg.appendChild(gEdges);
D.edges.forEach(e => {
  const a = pos[e.from], b = pos[e.to];
  if (!a || !b) return;
  const forward = b.ci > a.ci;
  const x1 = forward ? a.x + a.w : a.x, y1 = a.y + a.h/2;
  const x2 = forward ? b.x : b.x + b.w, y2 = b.y + b.h/2;
  const mx = (x1 + x2) / 2;
  const p = el('path', {
    class: 'edge' + (forward ? '' : ' back'),
    d: 'M'+x1+','+y1+' C'+mx+','+y1+' '+mx+','+y2+' '+x2+','+y2,
  });
  p.dataset.from = e.from; p.dataset.to = e.to;
  gEdges.appendChild(p); edgeEls.push(p);
});

/* nodes */
const nodeEls = {};
D.nodes.forEach(n => {
  const p = pos[n.id], c = COLOR(n.layer);
  const g = el('g', {class:'node', tabindex:'0', role:'button'});
  g.appendChild(el('rect', {x:p.x, y:p.y, width:p.w, height:p.h,
                            fill:'var(--panel-2)', stroke:c}));
  g.appendChild(el('rect', {x:p.x, y:p.y, width:3, height:p.h, fill:c, rx:1.5}));
  const short = n.id.replace(/^tools\./,'').replace(/^scripts\./,'');
  const t1 = el('text', {class:'n', x:p.x+11, y:p.y+13}); t1.textContent = short;
  const t2 = el('text', {class:'l', x:p.x+11, y:p.y+25});
  t2.textContent = n.lines + ' lines · ' + n.defs + ' defs';
  g.appendChild(t1); g.appendChild(t2);
  g.addEventListener('mouseenter', () => focus(n.id));
  g.addEventListener('mouseleave', () => focus(null));
  g.addEventListener('focus',      () => { focus(n.id); select(n.id); });
  g.addEventListener('click',      () => select(n.id));
  svg.appendChild(g); nodeEls[n.id] = g;
});

function focus(id){
  const all = Object.values(nodeEls);
  if (!id) { all.forEach(g => g.classList.remove('dim'));
             edgeEls.forEach(p => p.classList.remove('dim','on','out')); return; }
  const near = new Set([id]);
  D.edges.forEach(e => { if (e.from === id) near.add(e.to); if (e.to === id) near.add(e.from); });
  D.nodes.forEach(n => nodeEls[n.id].classList.toggle('dim', !near.has(n.id)));
  edgeEls.forEach(p => {
    const hit = p.dataset.from === id || p.dataset.to === id;
    p.classList.toggle('dim', !hit);
    p.classList.toggle('on', hit);
    p.classList.toggle('out', hit && p.dataset.from === id);
  });
}

const detail = document.getElementById('detail');
function select(id){
  const n = D.nodes.find(x => x.id === id);
  if (!n) { detail.innerHTML = '<p class="none">Hover a module to trace its dependencies; click to pin the detail here.</p>'; return; }
  const out = D.edges.filter(e => e.from === id).map(e => e.to).sort();
  const inc = D.edges.filter(e => e.to === id).map(e => e.from).sort();
  const link = m => '<li><button data-go="'+esc(m)+'">'+esc(m)+'</button></li>';
  const list = (arr, empty) => arr.length ? '<ul>'+arr.map(link).join('')+'</ul>'
                                          : '<p class="none">'+empty+'</p>';
  detail.innerHTML =
    '<h2>'+esc(n.id)+'</h2><div class="path">'+esc(n.file)+'</div>'
    + '<div class="stat"><span><b>'+n.lines+'</b> lines</span><span><b>'+n.defs+'</b> defs</span>'
    + '<span style="color:'+COLOR(n.layer)+'">'+esc(LABELS[n.layer])+'</span></div>'
    + (n.desc ? '<p>'+esc(n.desc)+'</p>'
              : '<p class="none">No note yet — add one in docs/repo_map_notes.json.</p>')
    + '<h3>Imports ('+out.length+')</h3>' + list(out, 'nothing first-party')
    + '<h3>Imported by ('+inc.length+')</h3>' + list(inc, 'nothing — an entry point or unused');
  detail.querySelectorAll('[data-go]').forEach(b =>
    b.addEventListener('click', () => { select(b.dataset.go); focus(b.dataset.go); }));
}
select(null);

/* ---- tool catalog ------------------------------------------------------- */
document.getElementById('toolrows').innerHTML = D.tools.map(t => {
  const impl = t.impl.length
    ? t.impl.map(i => '<b>'+esc(i.fn)+'</b>()' + (i.module ? '<br>'+esc(i.module) : '')).join('<br>')
    : '<span style="opacity:.5">no branch in execute_tool</span>';
  const params = t.params.length
    ? '<div class="pm">' + t.params.map(p =>
        (t.required.includes(p) ? '<span>'+esc(p)+'*</span>' : esc(p))).join(' · ') + '</div>'
    : '';
  return '<tr data-name="'+esc(t.name)+'"><td class="nm">'+esc(t.name)+'</td>'
       + '<td class="ds">'+esc(t.desc)+params+'</td>'
       + '<td class="im">'+impl+'</td></tr>';
}).join('');

/* ---- tabs + filter ------------------------------------------------------ */
const tabs = {modules:'view-modules', tools:'view-tools'};
Object.keys(tabs).forEach(k => {
  document.getElementById('tab-'+k).addEventListener('click', () => {
    Object.keys(tabs).forEach(j => {
      const on = j === k;
      document.getElementById('tab-'+j).setAttribute('aria-selected', on);
      document.getElementById(tabs[j]).classList.toggle('hidden', !on);
    });
  });
});

document.getElementById('q').addEventListener('input', e => {
  const q = e.target.value.trim().toLowerCase();
  D.nodes.forEach(n => nodeEls[n.id].classList.toggle('dim', !!q && !n.id.toLowerCase().includes(q)));
  document.querySelectorAll('#toolrows tr').forEach(r =>
    r.classList.toggle('hidden', !!q && !r.dataset.name.toLowerCase().includes(q)));
});
</script>
</body>
</html>
"""


def render(data: dict) -> str:
    return (TEMPLATE
            .replace("__DATA__", json.dumps(data, indent=1))
            .replace("__LAYERS__", json.dumps(LAYER_ORDER))
            .replace("__LABELS__", json.dumps(LAYER_LABEL)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the committed map is out of date")
    args = ap.parse_args()

    data = build()
    page = render(data)

    if args.check:
        current = OUT.read_text() if OUT.exists() else ""
        # the timestamp changes on every run; compare everything else
        strip = lambda s: "\n".join(
            l for l in s.splitlines() if '"generated"' not in l and '"sha"' not in l
        )
        if strip(current) != strip(page):
            print("static/repo_map.html is out of date — run: python scripts/build_repo_map.py")
            return 1
        print("repo map is up to date")
        return 0

    OUT.write_text(page)
    m = data["meta"]
    print(f"wrote {OUT.relative_to(ROOT)} — {m['modules']} modules, {m['deps']} dependencies, "
          f"{len(data['tools'])} tools, {m['loc']:,} lines @ {m['sha']}")

    missing = [n["id"] for n in data["nodes"] if not n["desc"]]
    if missing:
        print(f"\n{len(missing)} modules have neither a docstring nor a note "
              f"in docs/repo_map_notes.json:")
        for name in missing:
            print("   ", name)
    if data["undeclared"]:
        print("\ndispatch branches with no matching schema:", ", ".join(data["undeclared"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
