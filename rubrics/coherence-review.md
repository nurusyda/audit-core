# Rubric: System Coherence (CTL-0510 – CTL-0515)

Owned by principal-architect. Answers the question the other controls cannot:
**does this change clash with what already exists?**

Everything else in this repo is LOCAL — it reads the diff. Coherence is RELATIONAL.
A change can be correct, tested, secure, and still make the system worse as a whole.

## The four questions

1. **Does this duplicate something?** Not "is it similar" — is there already code that
   does this job? If yes, why is a second one better than extending the first?
2. **Does this contradict a decision?** Check `.audit/decisions.yaml`. A decision you
   are overturning is fine — but overturn it explicitly with `supersedes`, do not
   quietly contradict it.
3. **Who else is affected?** Changed a signature, a return shape, an error type, a
   config key? Everything downstream needs checking, not just what the tests cover.
4. **Does this add a second way to do something?** Two HTTP clients, two date
   libraries, two error shapes, two auth paths. Each one is a fork in the road that
   every future reader has to navigate.

## Reading CTL-0511 (reverse dependencies)

`unupdated` is the field that matters. Callers that exist and were NOT touched by this
change are the ones that will break. If the list is non-empty, either update them or
say explicitly why they are unaffected.

## Reading CTL-0513 (decisions)

Two kinds of output:
- **violations** — a `detect:` regex matched. Mechanical, reliable.
- **manual** — the decision applies to files you changed but has no regex. **These are
  YOUR job.** They are not passes. Read each one and confirm the change respects it.

## Reading CTL-0515 (semantic review) — read this before trusting it

The LLM layer reports a **hallucination rate** in every run. Read it.

- Claims marked `GROUNDED` passed two checks: the cited file/line/symbol exist, and
  the quoted code appears verbatim in the file. These are safe to act on.
- Claims marked `FABRICATED` or `UNGROUNDED` were discarded before you saw them. They
  are listed under `discarded` for transparency, not for action.
- A rising hallucination rate means the backend or the prompt has degraded. Above ~15%
  sustained, turn it off — a reviewer who half-trusts findings is worse off than one
  with none.

**The verifier only proves a citation is real. It does not prove the reasoning is
right.** A grounded claim can still be a wrong conclusion drawn from real code. Treat
grounded findings as "worth looking at", never as "confirmed".

## Adding a decision

When a review surfaces a rule the codebase should follow, write it down:

```yaml
- id: DEC-00NN
  decided: YYYY-MM-DD
  spec: 003-payments
  invariant: "One sentence. Testable if possible."
  scope: ["src/billing/**"]
  detect: "\\bfloat\\("        # optional; omit if not mechanically checkable
```

A decision with a `detect:` regex is enforced forever at zero cost. One without still
surfaces for human review. Both beat the rule living only in someone's memory.
