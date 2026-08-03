# Remediation: Committed Secret (CTL-0001)

**A secret that touched git is burned. Deleting it in the next commit does nothing.**
It is in the history, in every clone, in every fork, in CI logs, and in laptop backups.

## Do these in order. Order matters.

### 1. Revoke — first, before anything else
Rotate the credential at the provider. Do this before cleaning history. A cleaned history
with a live credential is worse than nothing, because it looks resolved.

### 2. Assess exposure
- How long was it in the repo?
- Who had clone access? Contractors? CI? Forks?
- Did the repo ever go public, even briefly?
- Check the provider's access logs for use from unexpected sources.

### 3. Rewrite history
```bash
git filter-repo --invert-paths --path path/to/file
# or, for a value inside a file:
git filter-repo --replace-text expressions.txt
```
Then force-push and require every collaborator to re-clone. Rebasing on top of the
rewrite reintroduces the secret.

Note: GitHub retains unreferenced objects. Contact support to purge, or treat the
credential as permanently compromised — which it is anyway, per step 1.

### 4. Prevent recurrence
- Secret in an environment variable or a secrets manager, never in a file
- `.env` in `.gitignore`, `.env.example` with placeholder values committed
- gitleaks in the pre-commit hook (this repo installs it)
- Short-lived credentials wherever the provider supports them

## Do not
- Do not just delete and commit — the history is the problem
- Do not assume a private repo is safe
- Do not skip revocation because rotation is inconvenient
