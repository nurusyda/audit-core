# Rubric: Operability & Rollback (CTL-0303)

Judgment review. Advisory. Owned by senior-devops.
The framing question for all of it: **what does the on-call person do at 3am?**

## Rollback
- [ ] The rollback command is written down, literally, as a command
- [ ] It has been executed at least once, not just documented
- [ ] What does rollback NOT undo? (data migrations, sent emails, third-party state)
- [ ] Time to roll back, measured
- [ ] Is a partial rollback possible, or is it all-or-nothing?

## Deploy safety
- [ ] Backward compatible with the currently-running version (they will coexist)
- [ ] Migration and code can be deployed independently
- [ ] Feature flag available for anything user-visible and risky
- [ ] Blast radius stated: who is affected if this is wrong?

## Terraform plan reading order
1. Anything marked `destroy` or `replace` — **stop here if it is stateful**
2. IAM and security group changes
3. Everything else

Most infrastructure disasters were visible in the plan and nobody read past screen one.

## Failure modes
- [ ] What happens if this dependency is unavailable?
- [ ] What happens if it is slow rather than down? (usually worse)
- [ ] Is there a limit on resource consumption?
- [ ] Does failure degrade gracefully or cascade?
