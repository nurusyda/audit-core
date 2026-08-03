#!/usr/bin/env bash
# loop.sh — the correction loop. Gate B runs, the agent fixes, gate B re-runs.
#
# CLAUDE.md tells the agent "max 3 rounds then escalate". That is an INSTRUCTION,
# and an agent that ignores it just keeps going. This file makes it a fact.
#
#   bash $AUDIT_CORE/loop.sh [max_rounds]
#
# Exits 0 when gate B is green, 1 when the budget is exhausted (escalate to human).
set -uo pipefail

MAX="${1:-3}"
CORE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUND=0

command -v claude >/dev/null 2>&1 || {
  echo "loop: 'claude' CLI not found. Install Claude Code, or run the gates manually."
  exit 2
}

while :; do
  ROUND=$((ROUND + 1))
  echo ""
  echo "=============== ROUND $ROUND / $MAX ==============="

  python3 "$CORE/runner/audit.py" --changed-only
  AUDIT_RC=$?
  python3 "$CORE/runner/coherence.py" || true
  COH_RC=$?

  if [ "$AUDIT_RC" -eq 0 ] && [ "$COH_RC" -eq 0 ]; then
    echo ""
    echo "loop: both gates green after $ROUND round(s)."
    python3 "$CORE/runner/semantic.py" || true    # advisory, never blocks
    python3 "$CORE/runner/report.py"
    echo ""
    echo "loop: STOP. Gate A is the human's. Read .audit/reports/change-report.md"
    exit 0
  fi

  if [ "$ROUND" -ge "$MAX" ]; then
    echo ""
    echo "loop: BUDGET EXHAUSTED after $MAX rounds. Escalating to human."
    echo "loop: unresolved findings:"
    python3 -c "
import json,pathlib
for f in ('.audit/last-run.json','.audit/coherence.json'):
    p=pathlib.Path(f)
    if p.exists():
        d=json.loads(p.read_text())
        for b in d.get('blocking_failures') or d.get('blocking') or []:
            print('   -',b)
"
    exit 1
  fi

  # Build the correction prompt from MACHINE OUTPUT, never from a summary.
  PROMPT=$(python3 - <<'PY'
import json, pathlib
parts = ["The audit gates are failing. Fix ONLY these findings. Do not refactor, "
         "do not add features, do not change anything not required by a finding below.\n"]
for f, key in (('.audit/last-run.json','blocking_failures'),
               ('.audit/coherence.json','blocking')):
    p = pathlib.Path(f)
    if not p.exists():
        continue
    d = json.loads(p.read_text())
    for r in d.get('results', []) if isinstance(d.get('results'), list) else []:
        if r.get('id') in (d.get(key) or []):
            parts.append(f"\n[{r['id']}] {r['title']}\n  {r.get('note','')}\n"
                         f"  {(r.get('output_tail') or '')[-700:]}")
    if isinstance(d.get('results'), dict):
        for cid, r in d['results'].items():
            if r.get('status') == 'fail':
                parts.append(f"\n[{cid}] {r['title']}\n"
                             f"  {json.dumps(r.get('findings', [])[:3], default=str)[:900]}")
parts.append("\nWhen done, stop. Do not run the gates yourself; the loop re-runs them.")
print("\n".join(parts))
PY
)

  echo "loop: sending correction prompt to Claude Code…"
  echo "$PROMPT" | claude -p --permission-mode acceptEdits || {
    echo "loop: claude invocation failed"; exit 2; }
done
