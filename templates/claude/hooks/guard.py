#!/usr/bin/env python3
"""
guard.py — PreToolUse hook. The hard floor.

WHY THIS EXISTS ON TOP OF DENY RULES
====================================
Per the Claude Code docs, Read and Edit deny rules apply to the built-in file tools
and to file commands Claude Code recognises in Bash (cat, head, tail, sed). They do
NOT apply to arbitrary subprocesses that open files themselves.

So this is blocked by a deny rule:

    sed -i 's/false/true/' .audit/approval.json

...and this is not:

    python3 -c "open('.audit/approval.json','w').write('{...}')"

Both forge the same signature. A rule that stops the obvious spelling and misses the
easy workaround is the kind of protection that reads as safety and provides none.

Hooks run BEFORE every other permission step, and a hook denial applies even in
bypassPermissions mode. Exit code 2 blocks the call.

Honest limit: this is pattern matching on a command string, and a determined agent
can evade pattern matching. It stops the CARELESS case — the agent on round 3 that
"helpfully" marks the audit green to get unstuck — which is the case you will
actually meet. CI re-running everything in a clean container from pinned audit-core
remains the real backstop.
"""

import json
import re
import sys

# Files that are EVIDENCE. If an agent can write these, every gate becomes theatre:
# it can forge your approval, fabricate a passing audit, or reset a ratchet baseline.
PROTECTED = [
    r"\.audit/approval\.json",
    r"\.audit/last-run\.json",
    r"\.audit/coherence\.json",
    r"\.audit/baselines/",
    r"\.claude/settings\.json",
    r"\.claude/hooks/",
    r"\.git/hooks/",
]

# Anything that could plausibly write. Deliberately broad — a false block is a
# five-second annoyance; a false pass is a silently ungated commit.
WRITERS = [
    r"\bpython3?\b.*\b(open|write_text|writelines|shutil|pathlib|os\.remove|unlink)\b",
    # No trailing \b: writeFileSync/appendFileSync/rmSync would escape it. The
    # 'Sync' suffix slipping past the boundary was a real miss found in testing.
    r"\bnode\b.*\b(writeFile|appendFile|createWriteStream|unlink|rm|rename|copyFile|mkdir|truncate)",
    r"\b(ruby|php|deno|bun)\b.*\b(write|unlink|remove|File\.open)",
    r"\bperl\b.*-[a-z]*i",
    r"\b(tee|dd|truncate|install)\b",
    r">>?\s*[^|&;]*",          # any shell redirection
    r"\b(mv|cp|rm|ln|touch|chmod|chown)\b",
    r"\bsed\b.*-[a-z]*i",
    r"\bawk\b.*>\s*",
    r"\becho\b.*>",
    r"\bprintf\b.*>",
    r"\bcat\b.*>",
]

# Commands that defeat the gates regardless of which file they touch.
FORBIDDEN = [
    (r"--no-verify", "bypasses the pre-commit and pre-push gates"),
    (r"\bgit\s+commit\b.*\s-\w*n\b", "git commit -n bypasses the pre-commit gate"),
    (r"\bgit\s+push\b.*--force", "force push can erase gated history"),
    (r"\bgit\s+push\b.*\s-f\b", "force push can erase gated history"),
    (r"gates\.py\s+approve", "approval is the human's; the agent cannot approve its own work"),
    (r"\bmake\s+approve\b", "approval is the human's; the agent cannot approve its own work"),
    (r"\bgit\s+reset\s+--hard", "discards work the gates have not seen"),
    (r"chmod\s+[-+]x\s+.*\.git/hooks", "disabling a hook disables the gate"),
]


def block(reason, detail=""):
    print(f"BLOCKED by audit guard: {reason}", file=sys.stderr)
    if detail:
        print(f"  {detail}", file=sys.stderr)
    print("  This is enforcement, not a suggestion. If you believe the gate is wrong,"
          " stop and escalate to the human rather than routing around it.",
          file=sys.stderr)
    sys.exit(2)          # exit 2 = deny, applies even in bypassPermissions


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)      # malformed input is not the agent's fault; do not block

    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    cmd = (payload.get("tool_input") or {}).get("command", "")
    if not cmd:
        sys.exit(0)

    for pattern, why in FORBIDDEN:
        if re.search(pattern, cmd, re.I):
            block(why, f"command: {cmd[:160]}")

    for prot in PROTECTED:
        if re.search(prot, cmd):
            for w in WRITERS:
                if re.search(w, cmd, re.I):
                    block(
                        "attempted write to a protected evidence file",
                        f"These files are the record the gates rest on. "
                        f"command: {cmd[:160]}")

    sys.exit(0)


if __name__ == "__main__":
    main()
