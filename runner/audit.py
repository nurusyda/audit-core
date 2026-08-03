#!/usr/bin/env python3
"""
audit.py — the gate B engine.

Design commitments, in order of importance:

1. FAIL CLOSED. An unresolvable check is SKIPPED and reported as such; it is never
   silently counted as a pass. A crash is a failure, not a pass.
2. EVIDENCE, NOT CLAIMS. Every result records the exact command, exit code, duration,
   and a hash of raw output. "Passed" with no artifact is meaningless.
3. TIER3 NEVER BLOCKS. Judgment findings are advisory, always, regardless of config.
   A flaky gate gets bypassed within two weeks and then you have no gate at all.
4. RATCHET BY DEFAULT. Absolute thresholds on an existing codebase mean red on day one,
   which means the whole system gets ignored on day two.

Usage:
    python audit.py --config .audit/config.yaml [--changed-only] [--json]
"""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("audit: PyYAML required.  pip install pyyaml")

SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]
CORE = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------

def load_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def load_controls():
    controls = {}
    for f in sorted((CORE / "controls").glob("*.yaml")):
        for c in load_yaml(f) or []:
            if c.get("retired"):
                continue
            if c["id"] in controls:
                sys.exit(f"audit: duplicate control id {c['id']} in {f}")
            controls[c["id"]] = c
    return controls


EXT_HINTS = {"python": [".py"], "go": [".go"], "java": [".java", ".kt"],
             "javascript": [".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"]}


def detect_stacks(root):
    """Detect stacks by lockfile/manifest presence. A repo may have several."""
    found = []
    for f in sorted((CORE / "adapters").glob("*.yaml")):
        ad = load_yaml(f)
        markers = (ad.get("detect") or {}).get("files") or []
        if any((root / m).exists() for m in markers):
            found.append(ad)
    if not found:
        # No manifest. Fall back to file extensions — a repo of .py files with no
        # requirements.txt would otherwise get ZERO python coverage, silently.
        exts = {Path(f).suffix for f in
                subprocess.run(["git", "ls-files"], cwd=root, capture_output=True,
                               text=True).stdout.split()}
        for name, hints in EXT_HINTS.items():
            if exts & set(hints):
                found.append(load_yaml(CORE / "adapters" / f"{name}.yaml"))
    if not found:
        found = [load_yaml(CORE / "adapters" / "generic.yaml")]
    return found


def expand_frameworks(cfg, controls):
    """Frameworks are filters. Returns the set of control ids they select."""
    fw_defs = load_yaml(CORE / "mappings" / "frameworks.yaml")
    selected, seen = set(), set()

    def pull(name):
        if name in seen:
            return
        seen.add(name)
        d = fw_defs.get(name)
        if d is None:
            print(f"audit: WARNING unknown framework '{name}' — ignored", file=sys.stderr)
            return
        if d.get("extends"):
            pull(d["extends"])
        selected.update(d.get("controls") or [])
        for group in ("control_map", "criteria_map", "requirement_map",
                      "article_map", "safeguard_map", "technique_map"):
            for ids in (d.get(group) or {}).values():
                selected.update(ids)

    for name in cfg.get("frameworks") or []:
        pull(name)
    return {cid for cid in selected if cid in controls}


def select_controls(cfg, controls):
    """
    A control is in scope if its owning skill is enabled AND
    (no frameworks configured OR the control is selected by one of them).
    Explicit disable_controls always wins.
    """
    skills = set(cfg.get("skills") or [])
    fw_ids = expand_frameworks(cfg, controls)
    disabled = set(cfg.get("disable_controls") or [])
    forced = set(cfg.get("enable_controls") or [])

    out = []
    for cid, c in controls.items():
        if cid in disabled:
            continue
        if cid in forced:
            out.append(c)
            continue
        if c.get("owner_skill") not in skills:
            continue
        if fw_ids and cid not in fw_ids:
            continue
        out.append(c)
    return sorted(out, key=lambda c: c["id"])


# ----------------------------------------------------------------------------
# Waivers
# ----------------------------------------------------------------------------

def load_waivers(root):
    p = root / ".audit" / "waivers.yaml"
    if not p.exists():
        return {}, []
    raw = load_yaml(p) or {}
    active, expired = {}, []
    today = date.today()
    for w in raw.get("waivers") or []:
        exp = w.get("expires")
        if isinstance(exp, str):
            exp = datetime.strptime(exp, "%Y-%m-%d").date()
        # YAML parses an unquoted date into a date object, which json cannot serialize.
        # Normalise every waiver record to plain strings before it can reach json.dump.
        def flat(rec, reason):
            return {k: (str(v) if isinstance(v, (date, datetime)) else v)
                    for k, v in rec.items()} | {"reason_invalid": reason}

        if exp is None:
            expired.append(flat(w, "no expiry date — waivers must expire"))
            continue
        if not w.get("owner") or not w.get("justification"):
            expired.append(flat(w, "missing owner or justification"))
            continue
        if exp < today:
            expired.append(flat(w, f"expired {exp}"))
            continue
        active[w["control"]] = {**w, "expires": str(exp)}
    return active, expired


# ----------------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------------

def in_scope_paths(control, changed_files):
    scope = control.get("scope") or {}
    pats = scope.get("paths")
    if not pats:
        return changed_files
    hit = [f for f in changed_files
           if any(fnmatch.fnmatch(f, p) for p in pats)]
    for p in scope.get("exclude_paths") or []:
        hit = [f for f in hit if not fnmatch.fnmatch(f, p)]
    return hit


def resolve_command(control, adapters):
    det = control.get("detect") or {}
    if det.get("command"):
        return det["command"], None
    key = det.get("adapter_key")
    if not key:
        return None, "no command or adapter_key"
    for ad in adapters:
        cmd = (ad.get("commands") or {}).get(key)
        if cmd == "SKIP":
            return None, f"not applicable to stack '{ad['name']}'"
        if cmd:
            return cmd, None
    return None, f"adapter_key '{key}' not bound for detected stacks"


MISSING_TOOL_MARKERS = ("command not found", "not found", "No such file or directory",
                        "is not recognized as an internal")


def tool_missing(code, output):
    """
    A missing scanner is NOT a finding. Reporting 'semgrep is not installed' as a
    critical SQL injection is the fastest way to make every result untrustworthy.
    It is also not a pass — it is an absence of coverage, and must say so.
    """
    if code != 127:
        return None
    noise = {"sh", "bash", "command", "not", "found", "line", "such", "no", "file",
             "or", "directory", "recognized", "as", "an", "internal"}
    for line in output.splitlines():
        if any(m in line for m in MISSING_TOOL_MARKERS):
            for tok in line.replace(":", " ").replace(",", " ").split():
                tok = tok.strip("'\"")
                if (tok and not tok.isdigit() and not tok.startswith("-")
                        and "/" not in tok and tok.lower() not in noise):
                    return tok
    return "unknown tool"


def run_cmd(cmd, root, timeout):
    started = time.time()
    try:
        proc = subprocess.run(cmd, shell=True, cwd=root, timeout=timeout,
                              capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out, round(time.time() - started, 2), None
    except subprocess.TimeoutExpired:
        return 124, "", timeout, f"timed out after {timeout}s"
    except Exception as exc:                                  # noqa: BLE001
        return 125, "", round(time.time() - started, 2), str(exc)


def extract_metric(spec, output):
    """Pull a number out of tool output. Supports 'json:$.a.b' and a regex with one group."""
    if not spec:
        return None
    if spec.startswith("json:"):
        path = spec[5:].lstrip("$.").split(".")
        try:
            cur = json.loads(output)
        except json.JSONDecodeError:
            m = re.search(r"[{\[].*[}\]]", output, re.S)
            if not m:
                return None
            try:
                cur = json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                return None
        return float(cur) if isinstance(cur, (int, float)) else None
    m = re.search(spec, output)
    return float(m.group(1)) if m else None


def judge_budget(value, budget, baseline):
    """Returns (passed, explanation). Ratchet compares to baseline; absolute to a limit."""
    lower_better = budget.get("direction", "lower_is_better") == "lower_is_better"
    if budget.get("mode") == "absolute":
        limit = budget["limit"]
        ok = value <= limit if lower_better else value >= limit
        return ok, f"{value:g} vs limit {limit:g}"
    if baseline is None:
        return True, f"{value:g} — baseline established, no comparison yet"
    tol = budget.get("tolerance_pct", 0) / 100.0
    ceiling = baseline * (1 + tol) if lower_better else baseline * (1 - tol)
    ok = value <= ceiling if lower_better else value >= ceiling
    return ok, f"{value:g} vs baseline {baseline:g} (allowed {ceiling:.4g})"


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def git(root, *args):
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True,
                              text=True).stdout.strip()
    except Exception:                                          # noqa: BLE001
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".audit/config.yaml")
    ap.add_argument("--changed-only", action="store_true",
                    help="Scan only files changed vs the merge base. Used by the pre-commit hook.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--update-baselines", action="store_true",
                    help="Record current tier2 metrics as the new baseline. Run on main only.")
    args = ap.parse_args()

    root = Path.cwd()
    cfg_path = root / args.config
    if not cfg_path.exists():
        sys.exit(f"audit: no config at {cfg_path}. Copy one from the project template.")
    cfg = load_yaml(cfg_path)

    controls = load_controls()
    selected = select_controls(cfg, controls)
    adapters = detect_stacks(root)
    waivers, bad_waivers = load_waivers(root)
    timeout = cfg.get("timeout_seconds", 300)

    baseline_path = root / ".audit" / "baselines" / "metrics.json"
    baselines = json.loads(baseline_path.read_text()) if baseline_path.exists() else {}

    base_ref = cfg.get("base_ref", "origin/main")
    if args.changed_only:
        diff = git(root, "diff", "--name-only", f"{base_ref}...HEAD")
        changed = [f for f in diff.splitlines() if f] or \
                  [f for f in git(root, "diff", "--name-only", "--cached").splitlines() if f]
    else:
        changed = [f for f in git(root, "ls-files").splitlines() if f]

    results, new_metrics = [], {}
    print(f"audit-core {(CORE / 'VERSION').read_text().strip()} | "
          f"stacks: {', '.join(a['name'] for a in adapters)} | "
          f"controls: {len(selected)}\n")

    for c in selected:
        cid, tier = c["id"], c["tier"]
        rec = {"id": cid, "title": c["title"], "domain": c["domain"], "tier": tier,
               "severity": c["severity"], "owner_skill": c["owner_skill"]}

        if c.get("type") == "attestation":
            rec.update(status="attestation", blocking=False,
                       note="Human process control — surfaces on the review checklist.")
            results.append(rec); continue

        if tier == "tier3":
            rec.update(status="review", blocking=False,
                       rubric=(c.get("detect") or {}).get("rubric"),
                       note="Judgment check — routed to gate A for human review.")
            results.append(rec); continue

        files = in_scope_paths(c, changed)
        if (c.get("scope") or {}).get("paths") and not files:
            rec.update(status="skipped", blocking=False, note="no files in scope changed")
            results.append(rec); continue

        cmd, why_not = resolve_command(c, adapters)
        if cmd is None:
            rec.update(status="skipped", blocking=False, note=why_not)
            results.append(rec); continue

        file_arg = " ".join(shlex.quote(f) for f in files[:400]) or "."
        cmd = cmd.replace("{{files}}", file_arg)
        code, output, dur, err = run_cmd(cmd, root, timeout)

        rec.update(command=cmd, exit_code=code, duration_s=dur,
                   evidence_sha256=hashlib.sha256(output.encode()).hexdigest()[:16],
                   output_tail=output.strip()[-1200:])

        missing = tool_missing(code, output)
        if missing:
            policy = cfg.get("missing_tool_policy", "warn")
            rec.update(status="error", missing_tool=missing,
                       note=f"'{missing}' is not installed — this control was NOT checked")
            rec["blocking"] = policy == "block"
            results.append(rec)
            print(f"  [ERR ] {cid}  {c['title'][:64]}  — {missing} not installed")
            continue

        if tier == "tier2":
            det = c["detect"]
            value = extract_metric(det.get("extract"), output)
            if value is None:
                rec.update(status="skipped", blocking=False,
                           note="metric not extractable — tool may not have run")
            else:
                metric = det["metric"]
                new_metrics[metric] = value
                ok, expl = judge_budget(value, det.get("budget", {}), baselines.get(metric))
                rec.update(status="pass" if ok else "fail", metric=metric,
                           value=value, baseline=baselines.get(metric), note=expl)
        else:
            failed = code != 0 or "NO_REDUCED_MOTION" in output or "RUNS_AS_ROOT" in output
            rec.update(status="fail" if failed else "pass")
            if err:
                rec.update(status="fail", note=err)

        if rec["status"] == "fail" and cid in waivers:
            rec.update(status="waived", waiver=waivers[cid],
                       note=f"waived until {waivers[cid]['expires']} by {waivers[cid]['owner']}")

        rec["blocking"] = rec["status"] == "fail" and c.get("blocking", True)
        results.append(rec)

        mark = {"pass": "PASS", "fail": "FAIL", "waived": "WAIV",
                "skipped": "SKIP"}.get(rec["status"], "----")
        print(f"  [{mark}] {cid}  {c['title'][:64]}"
              + (f"  — {rec.get('note')}" if rec.get("note") else ""))

    fail_on = cfg.get("fail_on", "high")
    threshold = SEVERITY_ORDER.index(fail_on)
    blockers = [r for r in results
                if r.get("blocking") and SEVERITY_ORDER.index(r["severity"]) >= threshold]

    if args.update_baselines and not blockers:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baselines.update(new_metrics)
        baseline_path.write_text(json.dumps(baselines, indent=2))
        print(f"\naudit: baselines updated ({len(new_metrics)} metrics)")

    summary = {
        "schema": 1,
        "core_version": (CORE / "VERSION").read_text().strip(),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": git(root, "rev-parse", "HEAD"),
        "diff_hash": hashlib.sha256(
            git(root, "diff", base_ref + "...HEAD").encode()).hexdigest()[:16],
        "stacks": [a["name"] for a in adapters],
        "frameworks": cfg.get("frameworks") or [],
        "skills": cfg.get("skills") or [],
        "counts": {s: sum(1 for r in results if r["status"] == s)
                   for s in ["pass", "fail", "waived", "skipped", "review", "attestation", "error"]},
        "blocking_failures": [r["id"] for r in blockers],
        "invalid_waivers": bad_waivers,
        "results": results,
    }

    out_path = root / ".audit" / "last-run.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))

    telemetry = root / ".audit" / "reports" / "control-stats.jsonl"
    with open(telemetry, "a") as fh:
        for r in results:
            fh.write(json.dumps({"ts": summary["timestamp"], "id": r["id"],
                                 "status": r["status"]}) + "\n")

    if args.json:
        print(json.dumps(summary, indent=2))

    c = summary["counts"]
    print(f"\n{c['pass']} passed · {c['fail']} failed · {c['waived']} waived · "
          f"{c['skipped']} skipped · {c['error']} not checked · {c['review']} for human review")

    if bad_waivers:
        print(f"\nEXPIRED/INVALID WAIVERS ({len(bad_waivers)}) — these no longer suppress anything:")
        for w in bad_waivers:
            print(f"  - {w.get('control')}: {w['reason_invalid']}")

    if blockers:
        print(f"\nBLOCKED by {len(blockers)} finding(s) at severity >= {fail_on}:")
        for b in blockers:
            print(f"  - {b['id']} [{b['severity']}] {b['title']}")
        return 1

    executed = c["pass"] + c["fail"] + c["waived"]
    if executed == 0 and selected and not cfg.get("allow_zero_coverage"):
        print("\n  NO COVERAGE — not a single control actually executed.")
        print("  Zero checks passed is not a pass. Likely causes: stack not detected,")
        print("  or no scanners installed. Set allow_zero_coverage: true to override.")
        return 1

    errored = [r for r in results if r["status"] == "error"]
    if errored:
        tools = sorted({r.get("missing_tool", "?") for r in errored})
        print(f"\n  INCOMPLETE COVERAGE — {len(errored)} control(s) could not run because "
              f"these tools are missing:\n    {', '.join(tools)}")
        print("  This is NOT a pass for those controls. Install them, or set")
        print("  missing_tool_policy: block  in .audit/config.yaml to enforce it.")
        for a in adapters:
            if a.get("install_hint"):
                print(f"    {a['name']}: {a['install_hint']}")
        print(f"\nGate B: PASSED on {c['pass']} checked control(s), "
              f"{len(errored)} UNVERIFIED")
        return 0

    print("\nGate B: PASSED")
    return 0


def _write_crash_artifact(exc):
    """
    A crash must NEVER leave the previous passing result in place — gates.py would
    read it and let the commit through. This was a real bug found in testing and it
    is the single most dangerous failure mode this system can have.
    """
    try:
        p = Path.cwd() / ".audit" / "last-run.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "schema": 1,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "crashed": True,
            "error": f"{type(exc).__name__}: {exc}",
            "counts": {k: 0 for k in ["pass", "fail", "waived", "skipped",
                                      "review", "attestation", "error"]},
            "blocking_failures": ["AUDIT_CRASHED"],
            "results": [],
        }, indent=2))
    except Exception:                                          # noqa: BLE001
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:                                   # noqa: BLE001
        _write_crash_artifact(exc)
        print(f"\naudit: CRASHED — {type(exc).__name__}: {exc}", file=sys.stderr)
        print("audit: recorded as a blocking failure. Gates will not pass.", file=sys.stderr)
        sys.exit(2)
