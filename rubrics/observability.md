# Rubric: Observability (CTL-0017, 0304)

Judgment review. Advisory. Shared by senior-devops and senior-appsec.
Nobody adds instrumentation during an incident. It happens now or never.

## Signals for any new service or endpoint
- [ ] Request rate, error rate, duration (RED) or equivalent
- [ ] Saturation of any bounded resource (pool, queue depth, memory)
- [ ] Health endpoint that actually checks dependencies, not just returns 200

## Security logging (CTL-0017)
Logged for every one of these, with actor, source, target, and outcome:
- [ ] Authentication success and failure
- [ ] Authorisation denial
- [ ] Privilege or role change
- [ ] Password or MFA change
- [ ] Data export or bulk read
- [ ] Admin actions

And: are those logs tamper-evident, retained long enough to investigate, and free of
credentials or personal data?

## Alerting
- [ ] Alerts on user-visible symptoms, not on CPU
- [ ] Every alert has a runbook link
- [ ] Every alert is actionable — if the response is "watch it", delete the alert
- [ ] Thresholds justified, not copied from a default

## Debuggability
- [ ] Correlation id propagated across service boundaries
- [ ] Errors logged with enough context to reproduce
- [ ] No log line that will fire thousands of times per second
