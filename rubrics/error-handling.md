# Rubric: Error Handling & Information Disclosure (CTL-0015)

Judgment review. Advisory. Owned by senior-appsec.

## What reaches the client
- [ ] No stack traces in any production response
- [ ] No framework or version strings in headers or error bodies
- [ ] No file paths, SQL fragments, or internal hostnames
- [ ] No distinction between "user does not exist" and "wrong password" (user enumeration)
- [ ] Generic message to the client, full detail in the log, linked by a reference id

## What reaches the log
- [ ] Enough context to reproduce
- [ ] No credentials, tokens, or personal data
- [ ] Errors not swallowed by a bare `except:` / `catch {}`
- [ ] Failure of a security control is logged loudly, not silently

## Failure behaviour
- [ ] Fails closed, not open — an auth check that errors must deny, not allow
- [ ] Partial failure leaves no inconsistent state
- [ ] Timeouts produce a distinguishable error, not a generic 500
