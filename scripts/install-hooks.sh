#!/usr/bin/env bash
# Install the local git hooks. Run once per project clone.
#   bash $AUDIT_CORE/scripts/install-hooks.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
CORE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS="$REPO_ROOT/.git/hooks"

mkdir -p "$HOOKS"

cat > "$HOOKS/pre-commit" <<HOOK
#!/usr/bin/env bash
# Fast local gate. Under 10 seconds by design — a slow hook is a bypassed hook.
# Secrets are checked HERE and not only in CI, because a credential is compromised
# the moment the commit object exists. CI is too late for that one check.
set -uo pipefail

export AUDIT_CORE="$CORE"
echo "  running local gate…"

if command -v gitleaks >/dev/null 2>&1; then
  if ! gitleaks git --staged --no-banner --redact .; then
    echo ""
    echo "  BLOCKED: a secret was detected in your staged changes."
    echo "  Remove it. If it was ever committed before, see:"
    echo "  \$AUDIT_CORE/rubrics/secrets-remediation.md"
    exit 1
  fi
else
  echo "  WARNING: gitleaks not installed — secret scanning SKIPPED, not passed."
  echo "  Install: https://github.com/gitleaks/gitleaks"
fi

python3 "\$AUDIT_CORE/runner/audit.py" --changed-only || exit 1
python3 "\$AUDIT_CORE/runner/gates.py" check --check-staged || exit 1
HOOK

cat > "$HOOKS/pre-push" <<HOOK
#!/usr/bin/env bash
# Push additionally requires the human approval token from gate A.
set -uo pipefail
export AUDIT_CORE="$CORE"
python3 "\$AUDIT_CORE/runner/gates.py" check --require-approval || exit 1
HOOK

chmod +x "$HOOKS/pre-commit" "$HOOKS/pre-push"
echo "Installed pre-commit and pre-push hooks."
echo "AUDIT_CORE=$CORE"
echo ""
echo "Add to your shell profile:  export AUDIT_CORE=$CORE"
