# Rubric: Test Quality (CTL-0504)

Judgment review. Advisory. Owned by senior-qa.

## The primary check
**For every bug fix: does the test fail against the pre-fix code?**

Verify it, do not assume it. `git stash` the fix, run the test, confirm red, restore.
A test that passes both before and after tests nothing, and this is the most common
defect in machine-written tests specifically.

## For each new or changed test
- [ ] Has at least one assertion on an OUTCOME, not just on a mock call
- [ ] Would fail if the implementation were replaced with a stub
- [ ] Tests behaviour, not private implementation detail
- [ ] Name says what is being verified, not what is being called
- [ ] No `sleep()` used for synchronisation
- [ ] No dependence on test execution order
- [ ] No shared mutable state with other tests
- [ ] Deterministic — clock, randomness, and network are controlled

## Coverage of the change
- [ ] Happy path
- [ ] Each error path, asserting the error is handled, not merely raised
- [ ] Boundaries: zero, one, many; empty, null, missing, wrong type
- [ ] The specific scenario from the bug report, if this is a fix

## The mutation question
On critical paths, ask by hand: if I flipped `>` to `>=`, inverted a boolean, or returned
early — would a test catch it? If not, the test is theatre. Full mutation testing is
expensive; asking the question on the diff is free.

## Output
For each test, one line: what real failure would this catch? If you cannot name one,
that is the finding.
