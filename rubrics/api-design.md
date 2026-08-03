# Rubric: API & Backend Design (CTL-0201, 0204, 0018)

Judgment review. Advisory. Owned by senior-backend.

## N+1 detection (CTL-0201)
Enable query logging and exercise the changed path.
- Count queries for 1 record, then for 10. If the count scales with rows, that is an N+1.
- Look specifically inside: serialisers, template loops, list comprehensions calling a
  property, and any `.count()` / `.exists()` inside iteration.
- Report the generated SQL AND the expected production row count. "This is N+1" is an
  observation; "this is 40,000 queries per request at current volume" is a decision.

## Idempotency (CTL-0204)
For every non-GET endpoint: what happens if the client sends it twice?
- Safe by nature (PUT to a fixed state) → fine.
- Creates a record, sends an email, charges money → needs an idempotency key with a
  dedupe window, or a natural unique constraint.
- Retried by a queue with no dedupe → **finding**.

## Rate limiting (CTL-0018)
Present on: login, password reset, MFA verify, token refresh, signup, search, export,
any endpoint that triggers an email or SMS, any expensive aggregation.
Keyed by what? IP alone is defeated by a botnet; account alone enables lockout-as-DoS.
Usually both.

## Timeouts & failure
- Every outbound call has an explicit timeout.
- What happens when it fires — retry, degrade, or fail? Written down?
- Is there a circuit breaker on anything called in a hot path?
- Are retries bounded and jittered? (Unjittered retries synchronise into a thundering herd.)

## API surface
- Status codes semantically correct
- Errors structured with a stable machine-readable code
- Collections paginated, with a documented maximum page size
- Breaking changes versioned; removal preceded by deprecation
- Field names consistent with the rest of the API
