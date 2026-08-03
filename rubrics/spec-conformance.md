# Rubric: Spec Conformance (CTL-0505)

Judgment review. Advisory. Owned by principal-architect.
This is the check that catches the failure everything else misses: code that is correct,
tested, and secure — and not what was asked for.

## Method
Open `.audit/specs/NNN-*.md` for this work. Build a table:

| Acceptance criterion | Met? | Evidence |
|---|---|---|
| (verbatim from spec) | yes/no/partial | file:line, or test name |

Verbatim. Do not paraphrase the criterion — paraphrasing is how it drifts.

## Then check the non-goals
For each item in the spec's "Non-goals" section: was it built anyway?

Scope addition is not a bonus. It is untested surface area, extra maintenance, and a
signal that the spec and the build have separated.

## Deviations
Any `no` or `partial` above needs:
- What was built instead
- Why the deviation happened
- Whether it was a deliberate decision or a discovery mid-build
- Whether the human needs to decide something

**Deviations go at the TOP of the gate A report.** A deviation the reviewer skims past is
identical to having no gate.

## Design questions
- [ ] New abstraction introduced? Does it have more than one real use case today?
- [ ] Second way to do something we already do one way?
- [ ] New dependency between modules that should not know about each other?
- [ ] Config flag added instead of a decision being made?
- [ ] "Temporary" workaround with no issue, owner, or date?
- [ ] Would a new engineer understand why this is shaped this way?
