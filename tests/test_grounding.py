"""
Regression suite for the grounding verifier.

This exists because a fabricated-symbol claim once passed as GROUNDED: the symbol
check was gated on a non-empty symbol table, so with an empty table it silently
skipped itself. A verification that does not run and reports success is the worst
failure this system can have.

    python3 tests/test_grounding.py
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runner"))
from semantic import verify, norm       # noqa: E402

SRC = '''"""User repository."""
import logging

log = logging.getLogger(__name__)


def find_user(user_id, tenant_id):
    rows = db.query("SELECT * FROM users WHERE id=? AND tenant=?", user_id, tenant_id)
    if not rows:
        return None
    for r in rows:
        if r.active:
            return r
    return None


def count_users(tenant_id):
    return db.scalar("SELECT count(*) FROM users WHERE tenant=?", tenant_id)
'''

CASES = [
    ("GROUNDED",   "genuine citation",          8, "find_user", None),
    ("GROUNDED",   "quote reindented by model", 8, "find_user", "STRIP"),
    ("GROUNDED",   "line drift within tolerance", 14, "find_user", None),
    ("FABRICATED", "invented symbol",           8, "lookup_account_by_email", None),
    ("FABRICATED", "invented quote",            8, "find_user",
     '    rows = db.query("SELECT * FROM users WHERE email=?", email)'),
    ("FABRICATED", "line beyond EOF",         420, "find_user", None),
    ("FABRICATED", "no quote field",            8, "find_user", "OMIT"),
]


def main():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "users.py").write_text(SRC)
        real = SRC.splitlines()[7]   # the db.query line

        failures = 0
        for expect, name, line, sym, quote in CASES:
            c = {"claim": "x", "existing_file": "users.py",
                 "existing_line": line, "existing_symbol": sym}
            if quote == "OMIT":
                pass
            elif quote == "STRIP":
                c["exact_quote"] = real.strip()
            else:
                c["exact_quote"] = quote or real

            got, why = verify(c, root, [])
            ok = got == expect
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {expect:<11} got={got:<11} {name}")
            if not ok:
                print(f"      reason: {why}")

        # The symbol check must run even with an empty symbol table.
        got, _ = verify({"claim": "x", "existing_file": "users.py",
                         "existing_line": 8, "existing_symbol": "totally_invented",
                         "exact_quote": real}, root, [])
        ok = got == "FABRICATED"
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  empty symbol table still verifies symbols")

    print(f"\n{'ALL PASSED' if not failures else f'{failures} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
