#!/usr/bin/env python3
"""
integrity.py — is the enforcement layer still there?

Deny rules only work if they exist. An agent that cannot edit .claude/settings.json
via the Edit tool could still have been asked to "clean up the config" in an earlier
session, or the file could be lost in a merge, a template refresh, or a tarball
extraction that quietly reverted it. (That last one happened three times while this
system was being built, to three different files, every time silently.)

So the presence of the guardrails is itself checked, in CI, where the agent has no
hands. Run from the project root:

    python3 integrity.py

Exit 0 = enforcement intact. Exit 1 = a required rule is missing or weakened.
"""

import json
import re
import sys
from pathlib import Path

REQUIRED_DENY = [
    # Evidence files. Writable evidence makes every gate theatre.
    "Edit(/.audit/approval.json)",
    "Edit(/.audit/last-run.json)",
    "Edit(/.audit/coherence.json)",
    "Edit(/.audit/baselines/**)",
    "Edit(/.git/hooks/**)",
    "Edit(/.claude/settings.json)",
    # Gate bypasses.
    "Bash(git commit --no-verify*)",
    "Bash(git push --no-verify*)",
    "Bash(git push --force*)",
    # Self-approval.
    "Bash(*gates.py approve*)",
    "Bash(make approve*)",
]

REQUIRED_ASK = [
    "Edit(/.audit/waivers.yaml)",
    "Edit(/.audit/config.yaml)",
]

problems, notes = [], []


def check_settings():
    p = Path(".claude/settings.json")
    if not p.exists():
        problems.append(".claude/settings.json is missing — NO permission enforcement "
                        "at all. Restore it from the project template.")
        return
    try:
        cfg = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        problems.append(f".claude/settings.json is not valid JSON ({e}). "
                        f"Claude Code will ignore it entirely.")
        return

    perms = cfg.get("permissions") or {}
    deny = set(perms.get("deny") or [])
    ask = set(perms.get("ask") or [])

    for rule in REQUIRED_DENY:
        if rule not in deny:
            problems.append(f"missing deny rule: {rule}")
    for rule in REQUIRED_ASK:
        if rule not in ask:
            problems.append(f"missing ask rule: {rule}")

    # The Write() trap: looks like protection, matches nothing.
    for rule in deny | ask:
        if rule.startswith("Write("):
            problems.append(
                f"{rule} is a NO-OP — Write() rules are never matched by file "
                f"permission checks. Use Edit() instead.")

    # A broad allow cannot cancel a deny, but it can widen everything else.
    for rule in perms.get("allow") or []:
        if rule in ("Bash", "Edit", "Read") or rule.strip() == "*":
            problems.append(f"allow rule '{rule}' is unscoped and auto-approves every "
                            f"call to that tool")

    hooks = (cfg.get("hooks") or {}).get("PreToolUse") or []
    if not any("guard.py" in json.dumps(h) for h in hooks):
        problems.append("PreToolUse guard hook is not registered — subprocess writes "
                        "to evidence files are unblocked")


def check_hook():
    p = Path(".claude/hooks/guard.py")
    if not p.exists():
        problems.append(".claude/hooks/guard.py is missing")
        return
    src = p.read_text()
    if "sys.exit(2)" not in src:
        problems.append("guard.py never exits 2 — it cannot actually block anything")
    # guard.py stores these as regexes with escaped dots, so match loosely rather
    # than on a literal filename — checking for the wrong spelling produced a false
    # FAIL on a perfectly intact hook.
    for label, pattern in (("approval.json", r"approval\\?\.json"),
                           ("last-run.json", r"last-run\\?\.json"),
                           ("--no-verify", r"--no-verify"),
                           ("gates.py approve", r"gates\\?\.py\\s\+approve|gates\\.py")):
        if not re.search(pattern, src):
            problems.append(f"guard.py no longer protects against '{label}'")


def check_hooks_installed():
    for h in ("pre-commit", "pre-push"):
        p = Path(".git/hooks") / h
        if not p.exists():
            notes.append(f".git/hooks/{h} not installed — run `make setup`. "
                         f"(CI still gates; local feedback is missing.)")
        elif not p.stat().st_mode & 0o111:
            problems.append(f".git/hooks/{h} exists but is not executable — "
                            f"git silently skips it")


def check_gitignored():
    gi = Path(".gitignore")
    if gi.exists() and re.search(r"^\s*\.claude/?\s*$", gi.read_text(), re.M):
        problems.append(".claude/ is gitignored — the enforcement layer will not "
                        "travel with the repo or reach CI")


def main():
    check_settings()
    check_hook()
    check_hooks_installed()
    check_gitignored()

    print("audit enforcement integrity\n")
    for n in notes:
        print(f"  NOTE  {n}")
    if notes:
        print()
    for p in problems:
        print(f"  FAIL  {p}")

    if problems:
        print(f"\n{len(problems)} problem(s). The permission layer is not intact.")
        print("Restore from the project template, then re-run.")
        return 1
    print(f"  OK    {len(REQUIRED_DENY)} deny rules, {len(REQUIRED_ASK)} ask rules, "
          f"guard hook registered")
    print("\nEnforcement intact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
