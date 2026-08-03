#!/usr/bin/env python3
"""
gates.py — enforcement. This is the part an agent cannot talk its way past.

Everything else in this repo is advice. This file is the wall.

Commands:
    check     Verify both gates for the current HEAD. Non-zero exit blocks the commit.
    approve   Record your Gate A approval, bound to the current commit hash.
    status    Human-readable current state.

Why approval is bound to a commit hash: otherwise "I approved this yesterday" silently
covers changes made since. It must be trivially invalidated by any new work.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AUDIT = Path(".audit")
LAST_RUN = AUDIT / "last-run.json"
APPROVAL = AUDIT / "approval.json"
MAX_AGE_MIN = 120


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()


def head():
    return git("rev-parse", "HEAD")


def staged_hash():
    return hashlib.sha256(git("diff", "--cached").encode()).hexdigest()[:16]


def fail(msg, *fixes):
    print(f"\n  GATE BLOCKED\n\n  {msg}\n")
    for f in fixes:
        print(f"    → {f}")
    print()
    return 1


def cmd_check(args):
    if not LAST_RUN.exists():
        return fail("Gate B has never run for this repo.",
                    "python $AUDIT_CORE/runner/audit.py --changed-only")

    try:
        run = json.loads(LAST_RUN.read_text())
    except json.JSONDecodeError as exc:
        return fail(f"Audit artifact is corrupt ({exc}). Treating as a failure.",
                    "Re-run: python $AUDIT_CORE/runner/audit.py --changed-only")

    if run.get("crashed"):
        return fail(f"The last audit run CRASHED: {run.get('error')}",
                    "A crash is a failure, never a pass.",
                    "Fix the cause and re-run the audit.")

    # Freshness by CONTENT, not only by clock. An artifact from a different diff is
    # not evidence about this one, however recently it was produced.
    current = hashlib.sha256(git("diff", "origin/main...HEAD").encode()).hexdigest()[:16]
    if run.get("diff_hash") and run["diff_hash"] != current:
        return fail("The audit result was produced from a different diff than the "
                    "one you are committing.",
                    "Re-run: python $AUDIT_CORE/runner/audit.py --changed-only")

    ts = datetime.fromisoformat(run["timestamp"].replace("Z","+00:00"))
    age = datetime.now(timezone.utc) - ts
    if age > timedelta(minutes=MAX_AGE_MIN):
        return fail(f"Audit result is {int(age.total_seconds() // 60)} minutes old "
                    f"(limit {MAX_AGE_MIN}). Stale results are not evidence.",
                    "Re-run: python $AUDIT_CORE/runner/audit.py --changed-only")

    if run["blocking_failures"]:
        return fail(f"Gate B failed: {len(run['blocking_failures'])} blocking finding(s) — "
                    f"{', '.join(run['blocking_failures'][:6])}",
                    "Fix them, or add a time-boxed waiver in .audit/waivers.yaml",
                    "See details: .audit/last-run.json")

    if run.get("invalid_waivers"):
        return fail(f"{len(run['invalid_waivers'])} waiver(s) expired or malformed. "
                    "An expired waiver stops suppressing its finding by design.",
                    "Renew with a new expiry, or fix the underlying issue")

    if args.require_approval:
        if not APPROVAL.exists():
            return fail("Gate A not approved — no human has reviewed this change.",
                        "Read: .audit/reports/change-report.md",
                        "Then: python $AUDIT_CORE/runner/gates.py approve")
        ap = json.loads(APPROVAL.read_text())
        if ap.get("head") != head():
            return fail(f"Approval was for commit {ap.get('head', '?')[:10]}, "
                        f"HEAD is now {head()[:10]}. The code changed after you approved it.",
                        "Regenerate the delta report:",
                        "  python $AUDIT_CORE/runner/report.py --since-approval",
                        "Then re-approve.")
        if args.check_staged and ap.get("staged_hash") not in (None, staged_hash()):
            return fail("Staged changes differ from what was approved.",
                        "Re-run Gate B and regenerate the report.")

    c = run["counts"]
    print(f"  Gate B: PASSED ({c['pass']} checks, {c['waived']} waived, {c['skipped']} skipped)")
    if args.require_approval:
        ap = json.loads(APPROVAL.read_text())
        print(f"  Gate A: APPROVED by {ap['by']} at {ap['at']}")
    print("  Proceeding.\n")
    return 0


def cmd_approve(args):
    if not LAST_RUN.exists():
        return fail("Cannot approve: Gate B has not run. Approving unaudited code "
                    "defeats the ordering the whole system is built on.")
    run = json.loads(LAST_RUN.read_text())
    if run["blocking_failures"]:
        return fail("Cannot approve while Gate B is failing. Fix or waive first — "
                    "approval is not an override.")

    report = AUDIT / "reports" / "change-report.md"
    if report.exists() and "_(unfilled)_" in report.read_text():
        return fail("The change report has unfilled sections. You would be approving "
                    "a summary nobody wrote.",
                    "Ask the agent to complete .audit/reports/change-report.md")

    APPROVAL.parent.mkdir(parents=True, exist_ok=True)
    APPROVAL.write_text(json.dumps({
        "head": head(),
        "staged_hash": staged_hash(),
        "diff_hash": run.get("diff_hash"),
        "by": args.by or git("config", "user.name") or "unknown",
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audit_timestamp": run["timestamp"],
        "note": args.note or "",
    }, indent=2))
    print(f"  Gate A approved for {head()[:10]}. Any further commit invalidates this.")
    return 0


def cmd_status(_args):
    print("\n  AUDIT STATUS\n")
    if LAST_RUN.exists():
        r = json.loads(LAST_RUN.read_text())
        c = r["counts"]
        state = "FAILING" if r["blocking_failures"] else "passing"
        print(f"  Gate B:  {state}")
        print(f"           {c['pass']} pass · {c['fail']} fail · {c['waived']} waived · "
              f"{c['skipped']} skip · {c['review']} awaiting your judgment")
        print(f"           core {r['core_version']} · stacks {', '.join(r['stacks'])}")
        print(f"           frameworks: {', '.join(r['frameworks']) or 'none'}")
        print(f"           run at {r['timestamp']}")
    else:
        print("  Gate B:  never run")
    if APPROVAL.exists():
        a = json.loads(APPROVAL.read_text())
        cur = "VALID" if a["head"] == head() else "STALE — code changed since"
        print(f"\n  Gate A:  approved by {a['by']} ({cur})")
    else:
        print("\n  Gate A:  not approved")
    print()
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check")
    c.add_argument("--require-approval", action="store_true")
    c.add_argument("--check-staged", action="store_true")
    c.set_defaults(fn=cmd_check)

    a = sub.add_parser("approve")
    a.add_argument("--by")
    a.add_argument("--note")
    a.set_defaults(fn=cmd_approve)

    s = sub.add_parser("status")
    s.set_defaults(fn=cmd_status)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
