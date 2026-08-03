#!/usr/bin/env python3
"""
coherence.py — does this change clash with what already exists?

Every control in v0.1.x is LOCAL: it reads the diff. Coherence is RELATIONAL — it
needs to know about code the diff does not touch. "Does this clash?" cannot be
answered by reading the change alone.

Everything in this file is DETERMINISTIC. No LLM. Same input, same output, every time.
The LLM layer lives in semantic.py and is tier3-advisory only, because a gate that
returns different answers on identical input gets bypassed within two weeks.

    python coherence.py --config .audit/config.yaml [--json]
"""

import argparse
import ast
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("coherence: PyYAML required")


# ---------------------------------------------------------------------------
# Repository model
# ---------------------------------------------------------------------------

class Repo:
    """
    A symbol/import/call model of the whole repository.

    Python is parsed with `ast` — exact. JS/TS is regex-scanned — approximate, and
    findings from it are reported at lower confidence. Never claim precision the
    parser cannot deliver; that is its own kind of hallucination.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.files = []
        self.imports = defaultdict(set)      # file -> {imported module}
        self.defs = {}                       # "file::symbol" -> {line, args, kind}
        self.calls = defaultdict(set)        # file -> {called symbol name}
        self.blocks = defaultdict(list)      # structural hash -> [(file, line, name)]
        self.parse_errors = []

    def scan(self):
        out = subprocess.run(["git", "ls-files"], cwd=self.root,
                             capture_output=True, text=True).stdout.split()
        for rel in out:
            p = self.root / rel
            if not p.is_file():
                continue
            if p.suffix == ".py":
                self.files.append(rel)
                self._scan_python(rel, p)
            elif p.suffix in (".js", ".jsx", ".ts", ".tsx"):
                self.files.append(rel)
                self._scan_js(rel, p)
        return self

    # -- Python: exact, via ast -------------------------------------------
    def _scan_python(self, rel, path):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError) as exc:
            self.parse_errors.append(f"{rel}: {exc}")
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.imports[rel].add(a.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    self.imports[rel].add(node.module)
                elif node.level:
                    self.imports[rel].add("." * node.level + (node.module or ""))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args]
                self.defs[f"{rel}::{node.name}"] = {
                    "file": rel, "name": node.name, "line": node.lineno,
                    "args": args, "kind": "function",
                    "arity": len(args),
                    "defaults": len(node.args.defaults),
                    "kwonly": [a.arg for a in node.args.kwonlyargs],
                }
                h = self._structural_hash(node)
                if h:
                    self.blocks[h].append((rel, node.lineno, node.name))
            elif isinstance(node, ast.ClassDef):
                self.defs[f"{rel}::{node.name}"] = {
                    "file": rel, "name": node.name, "line": node.lineno,
                    "kind": "class", "args": [], "arity": 0,
                    "defaults": 0, "kwonly": [],
                }
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    self.calls[rel].add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    self.calls[rel].add(fn.attr)

    @staticmethod
    def _structural_hash(node):
        """
        Hash the SHAPE of a function, ignoring names and literals. Two functions with
        the same control flow and operations hash identically even if every variable
        was renamed — which is exactly what copy-paste-then-rename produces.

        Bodies under 5 statements are ignored: short functions collide constantly and
        the noise would bury the real duplicates.
        """
        body = [n for n in ast.walk(node)
                if isinstance(n, (ast.If, ast.For, ast.While, ast.Try, ast.Assign,
                                  ast.Return, ast.Call, ast.Compare, ast.BinOp,
                                  ast.With, ast.Raise))]
        if len(body) < 5:
            return None
        shape = ",".join(type(n).__name__ for n in body)
        return hashlib.sha256(shape.encode()).hexdigest()[:16]

    # -- JS/TS: approximate, via regex ------------------------------------
    def _scan_js(self, rel, path):
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.parse_errors.append(f"{rel}: {exc}")
            return
        for m in re.finditer(r"""(?:import\s+.*?from\s+|require\()\s*['"]([^'"]+)['"]""",
                             src):
            self.imports[rel].add(m.group(1))
        for m in re.finditer(
                r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)",
                src, re.M):
            args = [a.strip().split("=")[0].strip()
                    for a in m.group(2).split(",") if a.strip()]
            self.defs[f"{rel}::{m.group(1)}"] = {
                "file": rel, "name": m.group(1),
                "line": src[:m.start()].count("\n") + 1,
                "args": args, "arity": len(args), "kind": "function",
                "defaults": 0, "kwonly": [], "approximate": True,
            }
        for m in re.finditer(r"^\s*(?:export\s+)?class\s+(\w+)", src, re.M):
            self.defs[f"{rel}::{m.group(1)}"] = {
                "file": rel, "name": m.group(1),
                "line": src[:m.start()].count("\n") + 1,
                "args": [], "arity": 0, "kind": "class",
                "defaults": 0, "kwonly": [], "approximate": True,
            }
        for m in re.finditer(r"\b(\w+)\s*\(", src):
            self.calls[rel].add(m.group(1))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def changed_files(root, base):
    d = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"],
                       cwd=root, capture_output=True, text=True).stdout.split()
    if not d:
        d = subprocess.run(["git", "diff", "--name-only", "--cached"],
                           cwd=root, capture_output=True, text=True).stdout.split()
    return [f for f in d if f]


def layer_of(path, layers):
    for name, patterns in layers.items():
        for pat in patterns if isinstance(patterns, list) else [patterns]:
            if fnmatch.fnmatch(path, pat):
                return name
    return None


def resolve_module(mod, from_file, repo):
    """
    Map an import to a real file in the repo. Handles dotted Python paths, relative
    imports, and JS relative specifiers. Returns None for third-party modules —
    which is correct: layering rules govern our own code, not our dependencies.
    """
    if mod.startswith("."):
        base = Path(from_file).parent
        for _ in range(len(mod) - len(mod.lstrip(".")) - 1):
            base = base.parent
        tail = mod.lstrip(".").replace(".", "/")
        cands = [str(base / tail) + ".py", str(base / tail / "__init__.py")]
    elif mod.startswith(("./", "../")):
        base = (Path(from_file).parent / mod).as_posix()
        cands = [base + e for e in (".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js")]
    else:
        path = mod.replace(".", "/")
        cands = [path + ".py", path + "/__init__.py",
                 path + ".ts", path + ".js", path + ".tsx", path + ".jsx"]
    norm = {str(Path(c)) for c in cands}
    for f in repo.files:
        if str(Path(f)) in norm:
            return f
    return None


def check_layering(repo, cfg, changed):
    """
    CTL-0510. Declare allowed import directions once; every violation after that is
    free to detect. This is the cheapest architectural-rot check that exists.
    """
    layers = (cfg.get("layers") or {}).get("paths") or {}
    allowed = (cfg.get("layers") or {}).get("allowed") or {}
    if not layers:
        return {"status": "skipped", "note": "no layers: declared in .audit/config.yaml",
                "findings": []}

    findings = []
    for f in changed:
        src_layer = layer_of(f, layers)
        if not src_layer:
            continue
        permitted = set(allowed.get(src_layer) or [])
        for imported in repo.imports.get(f, set()):
            target_file = resolve_module(imported, f, repo)
            target = layer_of(target_file, layers) if target_file else None
            if target and target != src_layer and target not in permitted:
                findings.append({
                    "file": f, "imports": imported,
                    "from_layer": src_layer, "to_layer": target,
                    "detail": f"{src_layer} may import {sorted(permitted) or 'nothing'}, "
                              f"not {target}",
                })
    return {"status": "fail" if findings else "pass", "findings": findings}


def check_reverse_deps(repo, root, base, changed):
    """
    CTL-0511. You changed a function signature. Who calls it, and were those callers
    updated in the same change? This is the single most common way a locally-correct
    edit breaks the system as a whole.
    """
    old = subprocess.run(["git", "stash", "list"], cwd=root,
                         capture_output=True, text=True)  # noqa: F841
    findings = []

    for f in changed:
        if not f.endswith(".py"):
            continue
        before = subprocess.run(["git", "show", f"{base}:{f}"], cwd=root,
                                capture_output=True, text=True)
        if before.returncode != 0:
            continue                                     # new file, no callers yet
        try:
            old_tree = ast.parse(before.stdout)
        except SyntaxError:
            continue

        old_sigs = {}
        for n in ast.walk(old_tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                old_sigs[n.name] = len(n.args.args)

        for name, old_arity in old_sigs.items():
            key = f"{f}::{name}"
            new = repo.defs.get(key)
            if new is None:
                callers = [c for c in repo.files
                           if c != f and name in repo.calls.get(c, set())]
                if callers:
                    findings.append({
                        "symbol": name, "file": f, "change": "removed",
                        "callers": callers[:10], "caller_count": len(callers),
                        "unupdated": [c for c in callers if c not in changed],
                    })
            elif new["arity"] != old_arity:
                callers = [c for c in repo.files
                           if c != f and name in repo.calls.get(c, set())]
                unupdated = [c for c in callers if c not in changed]
                if unupdated:
                    findings.append({
                        "symbol": name, "file": f,
                        "change": f"arity {old_arity} -> {new['arity']}",
                        "callers": callers[:10], "caller_count": len(callers),
                        "unupdated": unupdated,
                    })
    return {"status": "fail" if findings else "pass", "findings": findings}


def check_duplicates(repo, changed):
    """
    CTL-0512. Structural duplication — did this change add another copy of logic that
    already exists? Ratcheted by the caller: pre-existing duplicates are not the fail,
    ADDING to them is.
    """
    findings = []
    for h, locs in repo.blocks.items():
        if len(locs) < 2:
            continue
        touched = [l for l in locs if l[0] in changed]
        if not touched:
            continue                                     # pre-existing, not this change
        others = [l for l in locs if l[0] not in changed]
        if others:
            findings.append({
                "added": [{"file": f, "line": ln, "name": n} for f, ln, n in touched],
                "existing": [{"file": f, "line": ln, "name": n} for f, ln, n in others[:5]],
                "detail": "structurally identical control flow already exists",
            })
    return {"status": "fail" if findings else "pass", "findings": findings}


def check_decisions(root, changed):
    """
    CTL-0513. The decision registry. Specs are per-work-item and evaporate; decisions
    accumulate. This is what makes "does it clash with what we decided before"
    answerable at all.

    Only decisions carrying a `detect:` regex are checked mechanically. The rest are
    handed to the human in gate A — stated honestly rather than silently passed.
    """
    p = root / ".audit" / "decisions.yaml"
    if not p.exists():
        return {"status": "skipped", "note": "no .audit/decisions.yaml", "findings": [],
                "manual": []}

    raw = yaml.safe_load(p.read_text()) or {}
    decisions = raw.get("decisions") or []
    superseded = {d["supersedes"] for d in decisions if d.get("supersedes")}

    findings, manual = [], []
    for d in decisions:
        if d.get("id") in superseded or d.get("retired"):
            continue
        scope = d.get("scope") or ["**"]
        in_scope = [f for f in changed
                    if any(fnmatch.fnmatch(f, s) for s in scope)]
        if not in_scope:
            continue

        det = d.get("detect")
        if not det:
            manual.append({"id": d["id"], "invariant": d["invariant"],
                           "files": in_scope[:10]})
            continue

        hits = []
        for f in in_scope:
            fp = root / f
            if not fp.exists():
                continue
            for i, line in enumerate(fp.read_text(errors="replace").splitlines(), 1):
                if re.search(det, line):
                    hits.append({"file": f, "line": i, "text": line.strip()[:120]})
        if hits:
            findings.append({"id": d["id"], "invariant": d["invariant"],
                             "decided": str(d.get("decided", "")),
                             "violations": hits[:20], "count": len(hits)})
    return {"status": "fail" if findings else "pass",
            "findings": findings, "manual": manual}


def check_orphans(repo, root, base, changed):
    """
    CTL-0514. A replacement that left the original behind. Dead code the next person
    will find and use, not knowing it was superseded.
    """
    findings = []
    for key, d in repo.defs.items():
        if d["file"] not in changed or d["kind"] != "function":
            continue
        if d["name"].startswith("_") or d["name"] in ("main", "setup"):
            continue
        callers = [f for f in repo.files if d["name"] in repo.calls.get(f, set())]
        callers = [c for c in callers if c != d["file"]]
        internal = d["name"] in repo.calls.get(d["file"], set())
        if not callers and not internal:
            findings.append({"symbol": d["name"], "file": d["file"],
                             "line": d["line"],
                             "detail": "defined but never called anywhere in the repo"})
    return {"status": "fail" if findings else "pass", "findings": findings}


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".audit/config.yaml")
    ap.add_argument("--base", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path.cwd()
    cfg = yaml.safe_load((root / args.config).read_text()) or {}
    base = args.base or cfg.get("base_ref", "origin/main")

    changed = changed_files(root, base)
    if not changed:
        print("coherence: no changed files")
        return 0

    repo = Repo(root).scan()

    results = {
        "CTL-0510": {"title": "Import layering respected", **check_layering(repo, cfg, changed)},
        "CTL-0511": {"title": "Callers updated for changed signatures",
                     **check_reverse_deps(repo, root, base, changed)},
        "CTL-0512": {"title": "No new structural duplication",
                     **check_duplicates(repo, changed)},
        "CTL-0513": {"title": "Recorded decisions not violated",
                     **check_decisions(root, changed)},
        "CTL-0514": {"title": "No orphaned definitions",
                     **check_orphans(repo, root, base, changed)},
    }

    print(f"coherence | {len(repo.files)} files modelled · {len(changed)} changed · "
          f"{len(repo.defs)} symbols")
    if repo.parse_errors:
        print(f"  {len(repo.parse_errors)} file(s) could not be parsed — NOT checked:")
        for e in repo.parse_errors[:5]:
            print(f"    {e}")
    print()

    failed = []
    for cid, r in results.items():
        n = len(r.get("findings", []))
        mark = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}[r["status"]]
        extra = f"  — {r['note']}" if r.get("note") else (f"  — {n} finding(s)" if n else "")
        print(f"  [{mark}] {cid}  {r['title']}{extra}")
        if r["status"] == "fail":
            failed.append(cid)
            for f in r["findings"][:3]:
                print(f"          {json.dumps(f, default=str)[:190]}")

    manual = results["CTL-0513"].get("manual") or []
    if manual:
        print(f"\n  {len(manual)} recorded decision(s) apply to this change but cannot be")
        print("  checked mechanically — routed to gate A for human review:")
        for m in manual[:6]:
            print(f"    {m['id']}: {m['invariant'][:90]}")

    out = root / ".audit" / "coherence.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "changed_files": changed,
        "symbols_modelled": len(repo.defs),
        "parse_errors": repo.parse_errors,
        "results": results,
        "blocking": failed,
    }, indent=2, default=str))

    if args.json:
        print(json.dumps(results, indent=2, default=str))

    if failed:
        print(f"\ncoherence: BLOCKED by {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print("\ncoherence: PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                   # noqa: BLE001
        Path(".audit").mkdir(exist_ok=True)
        Path(".audit/coherence.json").write_text(json.dumps(
            {"crashed": True, "error": f"{type(exc).__name__}: {exc}",
             "blocking": ["COHERENCE_CRASHED"]}, indent=2))
        print(f"coherence: CRASHED — {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
