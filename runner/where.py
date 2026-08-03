#!/usr/bin/env python3
"""
where.py — "where am I, and what do I do next?"

You should not have to remember the workflow. Run this any time — start of a session,
after a break, when you have lost the thread — and it tells you the single next thing
to do and the exact command.

Both you and the agent run this. It is the same answer either way, which is the point:
you are never in a different place than the agent thinks you are.

    python where.py          # or: make where
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AUDIT = Path(".audit")
C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()


def base_ref(cfg_default="origin/main"):
    """The ref we diff against. Falls back sensibly when there is no remote yet."""
    cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    for ref in (cfg_default, "main", "master"):
        # A base that IS the current branch compares HEAD against itself and always
        # reports no work. Skip it.
        if ref == cur:
            continue
        if subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref],
                          capture_output=True).returncode == 0:
            return ref
    return None


def has_work(base):
    """
    Has anything actually been built? Uncommitted changes and unpushed commits are
    both unreliable signals — a fresh repo with everything committed and no remote
    has neither, and would look like nothing had been done.
    """
    files = set()
    if base:
        files |= set(subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"],
                                    capture_output=True, text=True).stdout.split())
    files |= set(subprocess.run(["git", "diff", "--name-only", "HEAD"],
                                capture_output=True, text=True).stdout.split())
    files |= set(subprocess.run(["git", "diff", "--name-only", "--cached"],
                                capture_output=True, text=True).stdout.split())
    if not files and not base:
        # No remote to compare against: treat any tracked source file as work.
        files = set(subprocess.run(["git", "ls-files"],
                                   capture_output=True, text=True).stdout.split())
    return {f for f in files
            if not f.startswith(".audit/") and f not in ("INTENT.md",)}


def load(p):
    try:
        return json.loads(p.read_text())
    except Exception:                                          # noqa: BLE001
        return None


def say(state, why, *actions, note=None):
    print(f"\n  {C['b']}YOU ARE HERE:{C['0']} {state}")
    print(f"  {C['dim']}{why}{C['0']}\n")
    print(f"  {C['b']}NEXT:{C['0']}")
    for a in actions:
        print(f"    {C['c']}{a}{C['0']}")
    if note:
        print(f"\n  {C['dim']}{note}{C['0']}")
    print()


def main():
    if not AUDIT.exists():
        say("Not set up yet",
            "This project has no .audit/ directory.",
            "make setup",
            note="If this isn't an audit-gated project, you're in the wrong directory.")
        return 0

    head = git("rev-parse", "--short", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    staged = bool(git("diff", "--cached", "--name-only"))
    unpushed = git("log", "@{u}..HEAD", "--oneline") if git("rev-parse", "--abbrev-ref",
                                                           "--symbolic-full-name", "@{u}") else ""
    specs = sorted(AUDIT.glob("specs/*.md"))
    specs = [s for s in specs if not s.name.startswith("000")]
    intent = Path("INTENT.md")

    run = load(AUDIT / "last-run.json")
    coh = load(AUDIT / "coherence.json")
    appr = load(AUDIT / "approval.json")
    report = AUDIT / "reports" / "change-report.md"

    print(f"\n  {C['dim']}{branch} @ {head}"
          f"{'  (uncommitted changes)' if dirty else ''}{C['0']}")

    # ---- 1. No intent, no spec ------------------------------------------
    if not specs and not intent.exists():
        say("Nothing started",
            "No spec, no intent document. Work should not begin here.",
            "Write what you want to build in plain language:  cp $AUDIT_CORE/templates/INTENT.md .",
            "Then open Claude Code and say: read INTENT.md and set this project up",
            note="Or write .audit/specs/001-<slug>.md yourself if you already know the shape.")
        return 0

    # ---- 2. Intent but no spec ------------------------------------------
    if not specs and intent.exists():
        say("Intent captured, not yet planned",
            "INTENT.md exists but no spec has been written from it.",
            "In Claude Code:  read INTENT.md, recommend a config, and write the first spec",
            note="The agent will propose skills, frameworks, and acceptance criteria. "
                 "You approve before any code is written.")
        return 0

    latest_spec = specs[-1]

    # ---- 3. Spec exists, nothing built ----------------------------------
    base = base_ref()
    work = has_work(base)
    if not work and not run:
        say("Planned, not built",
            f"Latest spec: {latest_spec.name}. No changes, no audit yet.",
            f"In Claude Code:  implement {latest_spec.name}",
            note="The agent loads the skills enabled in .audit/config.yaml and follows them.")
        return 0

    # ---- 4. Changes exist, audit never run or stale ----------------------
    cur_diff = git("diff", f"{base}...HEAD") if base else git("diff", "HEAD")
    import hashlib
    cur_hash = hashlib.sha256(cur_diff.encode()).hexdigest()[:16]

    stale = False
    if run:
        if run.get("crashed"):
            say("Audit crashed",
                f"Last run failed: {run.get('error', 'unknown')}",
                "make audit-fast",
                note="A crash is a failure, never a pass. Fix the cause and re-run.")
            return 0
        ts = datetime.fromisoformat(run["timestamp"].replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - ts
        stale = (run.get("diff_hash") and run["diff_hash"] != cur_hash) or age > timedelta(hours=2)

    if work and (not run or stale):
        say("Built, not checked",
            "There are changes the audit has not seen." if stale else "No audit has run yet.",
            "make audit-fast",
            "make coherence",
            note="Or run both with fixing: make loop")
        return 0

    # ---- 5. Audit failing ------------------------------------------------
    blockers = (run or {}).get("blocking_failures") or []
    coh_block = (coh or {}).get("blocking") or []
    if blockers or coh_block:
        acts = []
        print(f"\n  {C['b']}YOU ARE HERE:{C['0']} {C['r']}Gate B failing{C['0']}")
        print(f"  {C['dim']}These must be fixed, waived, or escalated:{C['0']}\n")
        for b in blockers:
            hit = next((r for r in (run.get("results") or []) if r.get("id") == b), {})
            print(f"    {C['r']}{b}{C['0']}  {hit.get('title', '')}")
            if hit.get("note"):
                print(f"        {C['dim']}{hit['note'][:100]}{C['0']}")
        for b in coh_block:
            r = (coh.get("results") or {}).get(b, {})
            print(f"    {C['r']}{b}{C['0']}  {r.get('title', '')}")
        print(f"\n  {C['b']}NEXT:{C['0']}")
        print(f"    {C['c']}make loop{C['0']}       # agent fixes, re-runs, max 3 rounds")
        print(f"    {C['dim']}or fix by hand, then: make audit-fast{C['0']}")
        print(f"    {C['dim']}or if genuinely accepted risk: add to .audit/waivers.yaml "
              f"with an owner and expiry{C['0']}\n")
        return 0

    # ---- 6. Green, no report ---------------------------------------------
    if not report.exists():
        say("Checks pass, nothing to review yet",
            "Gate B is green. The change report has not been generated.",
            "make report",
            note="Then read it. That is Gate A, and it is yours.")
        return 0

    unfilled = "_(unfilled)_" in report.read_text()
    if unfilled:
        say("Report generated, not written",
            "The change report has sections the agent has not filled in.",
            "In Claude Code:  fill in .audit/reports/change-report.md",
            note="Do not approve an empty summary — that defeats the whole gate.")
        return 0

    # ---- 7. Awaiting your review ------------------------------------------
    if not appr or appr.get("head") != git("rev-parse", "HEAD"):
        reason = ("The code changed after your last approval."
                  if appr else "Nobody has reviewed this yet.")
        say(f"{C['y']}Waiting for you{C['0']}",
            reason,
            "less .audit/reports/change-report.md",
            "make approve          # after you have actually read it",
            note="Rejecting is fine — tell the agent what to change, then: make delta")
        return 0

    # ---- 8. Approved -----------------------------------------------------
    if dirty or staged:
        say(f"{C['g']}Approved — ready to commit{C['0']}",
            "Both gates pass and you have signed off.",
            'git add -A && git commit -m "..."',
            "git push")
        return 0
    if unpushed:
        say(f"{C['g']}Committed — ready to push{C['0']}",
            f"{len(unpushed.splitlines())} commit(s) not yet on the remote.",
            "git push",
            note="pre-push re-checks both gates.")
        return 0

    say(f"{C['g']}All clear{C['0']}",
        "Everything committed, pushed, and approved. Nothing outstanding.",
        "Start the next piece:  write .audit/specs/"
        f"{int(latest_spec.name[:3]) + 1:03d}-<slug>.md",
        note="Discuss it first. The spec is the conclusion, not the opening move.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                   # noqa: BLE001
        print(f"\n  where: could not determine state — {type(exc).__name__}: {exc}")
        print("  Fall back to: make status\n")
        sys.exit(0)
