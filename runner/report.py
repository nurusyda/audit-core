#!/usr/bin/env python3
"""
report.py — builds the gate A review artifact.

The design point: a free-form prose summary can omit things, and you would never know.
So this script extracts the FACTS mechanically from the diff — files, dependencies,
network calls, auth touches, migrations — and leaves clearly marked slots for the agent
to fill in plain-language explanation.

You are reviewing a table you can trust plus prose you can check against it.

Usage:  python report.py [--out .audit/reports/change-report.md]
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Patterns that mean "a human should look at this line", with why-it-matters text.
RISK_SIGNALS = [
    (r"\b(fetch|axios|requests\.|http\.|HttpClient|urlopen)\b",
     "new outbound network call", "Where does this go? Does it have a timeout?"),
    (r"\b(exec|eval|system|subprocess|child_process|Runtime\.getRuntime)\b",
     "code or shell execution", "Can any user input reach this? That would be RCE."),
    (r"\b(password|secret|token|api[_-]?key|credential|private[_-]?key)\b",
     "credential handling", "Is this read from the environment, never hardcoded?"),
    (r"\b(authorize|authenticate|isAdmin|hasRole|permission|can[A-Z])\b",
     "authorisation logic", "Is the check server-side and tied to the requesting user?"),
    (r"\b(DROP|ALTER|TRUNCATE|DELETE FROM)\b",
     "destructive data operation", "Is this reversible? Is there a backup?"),
    (r"\b(CORS|Access-Control-Allow-Origin)\b",
     "cross-origin policy", "Is the origin list explicit rather than '*'?"),
    (r"\b(innerHTML|dangerouslySetInnerHTML|v-html|\|\s*safe)\b",
     "raw HTML injection", "Is this content ever attacker-controlled?"),
    (r"\b(pickle|yaml\.load|ObjectInputStream|unserialize)\b",
     "deserialisation", "Untrusted input here is remote code execution."),
    (r"\b(setTimeout\(\s*0|sleep\(|retry|backoff)\b",
     "timing or retry logic", "Is the retried operation idempotent?"),
]

DEP_FILES = ["package.json", "requirements.txt", "pyproject.toml", "go.mod",
             "pom.xml", "build.gradle", "Gemfile", "Cargo.toml"]


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--out", default=".audit/reports/change-report.md")
    ap.add_argument("--since-approval", action="store_true",
                    help="Round 2+: report only what changed since the last approval.")
    args = ap.parse_args()

    base = args.base
    approval = Path(".audit/approval.json")
    if args.since_approval and approval.exists():
        prev = json.loads(approval.read_text()).get("head")
        if prev:
            base = prev

    stat = git("diff", "--numstat", f"{base}...HEAD").strip().splitlines()
    files = []
    for line in stat:
        parts = line.split("\t")
        if len(parts) == 3:
            add, rem, path = parts
            files.append({"path": path, "added": add, "removed": rem})

    if not files:
        print("report: no changes vs", base)
        return 0

    diff = git("diff", "-U0", f"{base}...HEAD")
    added_lines = [l[1:] for l in diff.splitlines()
                   if l.startswith("+") and not l.startswith("+++")]

    flags = {}
    for pattern, label, question in RISK_SIGNALS:
        hits = [l.strip()[:120] for l in added_lines if re.search(pattern, l, re.I)]
        if hits:
            flags[label] = {"question": question, "count": len(hits), "sample": hits[:4]}

    dep_changes = [f["path"] for f in files if Path(f["path"]).name in DEP_FILES]
    new_deps = []
    if dep_changes:
        for l in added_lines:
            m = re.search(r'^\s*"?([a-zA-Z0-9@._/-]+)"?\s*[:=><~^]+\s*"?([0-9][^",\s]*)', l)
            if m:
                new_deps.append(f"{m.group(1)} {m.group(2)}")

    last_run = Path(".audit/last-run.json")
    audit = json.loads(last_run.read_text()) if last_run.exists() else None
    review_items = [r for r in (audit or {}).get("results", [])
                    if r["status"] in ("review", "attestation")]

    head = git("rev-parse", "HEAD").strip()
    total_add = sum(int(f["added"]) for f in files if f["added"].isdigit())
    total_rem = sum(int(f["removed"]) for f in files if f["removed"].isdigit())

    L = []
    w = L.append
    w("# Change Report — for your review (Gate A)\n")
    w(f"**Commit:** `{head[:10]}` · **Compared against:** `{base}` · "
      f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}Z\n")
    w(f"**Size:** {len(files)} files · +{total_add} / −{total_rem} lines\n")

    if audit:
        c = audit["counts"]
        state = "PASSED" if not audit["blocking_failures"] else "FAILED"
        w(f"**Automated audit (Gate B):** {state} — {c['pass']} passed, "
          f"{c['fail']} failed, {c['waived']} waived, {c['skipped']} skipped\n")
    else:
        w("**Automated audit (Gate B):** NOT RUN — do not approve until it has.\n")

    w("\n---\n")
    w("## 1. What this does, in plain language\n")
    w("<!-- AGENT: fill this in. Rules:\n"
      "     - No jargon. If you must use a technical term, define it in the same sentence.\n"
      "     - Say what CHANGED for a user of this system, not what code you wrote.\n"
      "     - State what you did NOT do, and anything you decided on your own.\n"
      "     - If you were unsure about something, say so here. That is the point of this gate. -->\n")
    w("_(unfilled)_\n")

    w("\n## 2. Why it was done this way\n")
    w("<!-- AGENT: the alternatives you considered and why you rejected them.\n"
      "     One short paragraph. If there was no real choice, say that. -->\n")
    w("_(unfilled)_\n")

    w("\n## 3. Files touched\n\n| File | + | − | What changed |\n|---|---|---|---|")
    for f in sorted(files, key=lambda x: -(int(x["added"]) if x["added"].isdigit() else 0))[:60]:
        w(f"| `{f['path']}` | {f['added']} | {f['removed']} | <!-- AGENT: one line --> |")
    if len(files) > 60:
        w(f"\n_…and {len(files) - 60} more files._")

    w("\n## 4. Things worth a second look\n")
    if flags:
        w("These are patterns the diff introduced that carry risk. Each has a question "
          "you should be able to answer before approving.\n")
        for label, d in flags.items():
            w(f"\n**{label}** — {d['count']} occurrence(s)")
            w(f"\n> {d['question']}\n")
            for s in d["sample"]:
                w(f"    {s}")
    else:
        w("No high-risk patterns detected in the added lines.\n")

    w("\n## 5. Dependencies\n")
    if new_deps:
        w("New or changed packages. Each one is code you now run and are responsible for:\n")
        for d in sorted(set(new_deps))[:30]:
            w(f"- `{d}`")
    elif dep_changes:
        w("Dependency manifests changed but no version pins were parsed — check manually.\n")
    else:
        w("No dependency changes.\n")

    w("\n## 6. Judgment items — machines cannot check these\n")
    if review_items:
        w("The audit routed these to you deliberately. They are the ones that matter most.\n")
        for r in review_items:
            kind = "process" if r["status"] == "attestation" else "judgment"
            w(f"\n- [ ] **{r['id']}** ({kind}, {r['severity']}) — {r['title']}")
            if r.get("rubric"):
                w(f"      _rubric: `{r['rubric']}`_")
    else:
        w("None selected by the current configuration.\n")

    w("\n---\n")
    w("## Decision\n")
    w("```\nAPPROVE:  python runner/gates.py approve\n"
      "REJECT:   tell the agent what to change. It will re-run Gate B, then\n"
      "          regenerate this report showing only the delta.\n```\n")
    w("_Approval is bound to the commit hash above. Any new commit invalidates it._\n")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L))
    print(f"report: wrote {out} ({len(files)} files, {len(flags)} risk flags, "
          f"{len(review_items)} judgment items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
