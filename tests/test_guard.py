"""
Regression suite for the PreToolUse guard hook.

Exists because `node -e "fs.writeFileSync('.audit/baselines/metrics.json', ...)"`
walked straight past the first version: the regex required a word boundary after
'writeFile', and the 'S' of 'Sync' is a word character. The rule looked correct,
read correctly, and blocked nothing.

Every entry below is an evasion route that must stay closed, or a normal command
that must stay open. Run from a project root containing .claude/hooks/guard.py:

    python3 tests/test_guard.py [path/to/project]
"""
import json
import subprocess
import sys
from pathlib import Path

BLOCK = [
    ("git commit --no-verify", 'git commit --no-verify -m "x"'),
    ("git commit -n", 'git commit -n -m "x"'),
    ("git push --force", "git push --force origin main"),
    ("git push -f", "git push -f origin main"),
    ("git reset --hard", "git reset --hard HEAD~3"),
    ("self-approve via gates.py", "python3 $AUDIT_CORE/runner/gates.py approve"),
    ("self-approve via make", "make approve"),
    ("sed -i on approval", "sed -i 's/a/b/' .audit/approval.json"),
    ("python open() write", "python3 -c \"open('.audit/approval.json','w').write('{}')\""),
    ("python pathlib write", "python3 -c \"import pathlib;pathlib.Path('.audit/last-run.json').write_text('{}')\""),
    ("node writeFileSync", "node -e \"require('fs').writeFileSync('.audit/baselines/metrics.json','{}')\""),
    ("node appendFileSync", "node -e \"require('fs').appendFileSync('.audit/last-run.json','x')\""),
    ("echo redirect", 'echo "{}" > .audit/last-run.json'),
    ("printf redirect", 'printf "{}" > .audit/coherence.json'),
    ("tee to evidence", 'echo "{}" | tee .audit/approval.json'),
    ("cp over evidence", "cp /tmp/fake.json .audit/last-run.json"),
    ("mv over evidence", "mv /tmp/fake.json .audit/approval.json"),
    ("rm a git hook", "rm .git/hooks/pre-commit"),
    ("chmod -x a git hook", "chmod -x .git/hooks/pre-commit"),
    ("edit settings.json", "sed -i 's/deny/allow/' .claude/settings.json"),
    ("disable the guard", "rm .claude/hooks/guard.py"),
]

ALLOW = [
    ("run the audit", "make audit-fast"),
    ("run coherence", "make coherence"),
    ("read audit result", "cat .audit/last-run.json"),
    ("read approval", "cat .audit/approval.json"),
    ("normal commit", 'git commit -m "fix: thing"'),
    ("normal push", "git push"),
    ("write source", 'echo "x=1" > src/app.py'),
    ("run tests", "pytest -q"),
    ("read a spec", "cat .audit/specs/001-x.md"),
    ("write a spec", "cat > .audit/specs/002-y.md << EOF"),
    ("install deps", "pip install requests"),
    ("git status", "git status --short"),
]


def run(hook, cmd):
    r = subprocess.run([sys.executable, str(hook)],
                       input=json.dumps({"tool_name": "Bash",
                                         "tool_input": {"command": cmd}}),
                       capture_output=True, text=True)
    return r.returncode == 2


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    hook = root / ".claude" / "hooks" / "guard.py"
    if not hook.exists():
        print(f"guard hook not found at {hook}")
        return 1

    fails = 0
    for name, cmd in BLOCK:
        ok = run(hook, cmd)
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  block  {name}")
    print()
    for name, cmd in ALLOW:
        ok = not run(hook, cmd)
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  allow  {name}")

    print(f"\n{'ALL PASSED' if not fails else f'{fails} FAILED'}"
          f"  ({len(BLOCK)} block + {len(ALLOW)} allow cases)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
