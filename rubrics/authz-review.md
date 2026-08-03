# Rubric: Authorisation & Access Control (CTL-0006, 0007, 0013)

Judgment review. Advisory — never blocks. Owned by senior-appsec.

## Method

Do not scan for patterns. Enumerate, then trace.

1. **List every endpoint the diff adds or changes.** Method, path, auth requirement.
2. For each, answer these four questions in writing:

### Q1 — Who can reach this?
Unauthenticated / any authenticated user / specific role / resource owner only.
State it explicitly. "Probably logged in" is not an answer.

### Q2 — Where does the identity come from?
Session or verified token → good.
Request body, query param, or header the client controls → **finding**.

### Q3 — Is the resource query scoped to that identity?
```
# finding
Order.find(request.params.id)

# correct
Order.find(id: request.params.id, user_id: session.user_id)
```
The first one is broken object-level authorisation. This is the most common serious API
bug in existence and it looks completely normal.

### Q4 — What is the worst case if the check is wrong?
Read one record / read all records / read across tenants / write / delete / escalate.

## Additional checks

- Is authorisation enforced in exactly one place, or duplicated with a chance to diverge?
- Is there a second path to the same resource (admin route, export, GraphQL, batch endpoint)?
- Are ids sequential integers? Even correct authz leaks existence and volume.
- On failure, does it return 404 rather than 403? (403 confirms the resource exists.)

## SSRF (CTL-0013)
If any URL comes from user input: is there an allowlist of hosts? Is redirect following
disabled or re-validated? Is the cloud metadata endpoint (169.254.169.254) blocked?
DNS rebinding is defeated by resolving once and connecting to the resolved IP.

## Output
For each endpoint: a row with the four answers. Any Q2 or Q3 failure is a CRITICAL finding
with the data path written out.
