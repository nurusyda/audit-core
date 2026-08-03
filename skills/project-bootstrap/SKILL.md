---
name: project-bootstrap
description: >
  Turn a rough idea into a configured, gated project. Use when a repository has an
  INTENT.md but no spec, when the user says they want to start something new, when
  .audit/config.yaml is still at defaults, or when the user asks what kind of project
  this should be or which skills to enable. Also use when the user describes something
  they want to build without having written anything down yet — capture it into
  INTENT.md first, then proceed.
owns_controls: none
---

# Project Bootstrap

Your job is to get from "I want to build a thing" to "the first spec is written and
the gates are configured correctly" — without the user having to remember any of the
rules.

You are doing the remembering. That is the entire point of this skill.

## Order of work

**1. Read `INTENT.md`.** If it does not exist, ask the user to describe the idea in
chat and write it into `INTENT.md` yourself from what they say. Do not skip this — the
raw idea in their words is the thing everything else is checked against later.

**2. Ask about gaps, but only real ones.** If the intent doesn't say whether it handles
personal data, ask — that changes which frameworks apply. If it doesn't say what
language, ask. Do NOT ask questions the document already answers, and do not ask more
than three at once.

**3. Recommend a configuration, with reasons.** Never just set it. Show the user:

```
Recommended for this project:

  skills:
    senior-appsec        — you're handling user accounts
    senior-backend       — API and database work
    senior-qa            — always
    principal-architect  — always
  NOT enabling:
    senior-frontend      — no UI in scope per your non-goals
    senior-uiux          — same
    senior-devops        — no infra yet; turn on when you deploy
    senior-data          — no personal data beyond email; revisit if that changes

  frameworks:
    owasp-asvs-L2        — sensible default for anything with user accounts
  NOT enabling:
    pci-dss-4, hipaa     — you don't touch card or health data
```

Then wait for them to agree or adjust. It is their project.

**4. Write the first spec** to `.audit/specs/001-<slug>.md` from
`$AUDIT_CORE/templates/spec.md`. Fill every section. In particular:
- **Acceptance criteria** must be testable statements, because CTL-0505 checks the
  build against them verbatim.
- **Non-goals** come straight from the intent's "must NOT do" section.
- **Open questions** come from "things I'm unsure about". Do not resolve these
  silently — leave them listed.

**5. Seed `.audit/decisions.yaml`** with anything from the intent that is a standing
rule rather than a one-off — "must run offline", "Postgres, not MySQL", "no external
APIs". These outlive the spec.

**6. Write the README skeleton** from `$AUDIT_CORE/templates/README.md`. Fill in the
title, the one-paragraph description, and the honest caveat. Leave the rest as headings
to be filled as the project grows — an outline is useful; invented content is not.

**7. Stop.** Show the user the spec, the config, and the README. No code until they say go.

## What you must not do

- **Do not start coding from INTENT.md.** The intent is raw; the spec is the agreement.
  Building straight from the intent is exactly the scope drift CTL-0505 exists to catch.
- **Do not enable every skill "to be safe".** Every enabled skill adds controls, and a
  wall of irrelevant findings on day one teaches the user to ignore all of them. Enable
  what applies now; say what you left off and when to revisit.
- **Do not enable a compliance framework the user has not asked for.** `pci-dss-4` when
  there are no card payments produces permanent red on controls that will never apply.
- **Do not invent requirements.** If the intent is silent on something, it is an open
  question, not an assumption.

## README conventions

Default to `$AUDIT_CORE/templates/README.md`. Its ordering is deliberate:
**what it is → what it can't do → how it works → how to run it → how to be careful.**
A reader should gain something even if they stop after any section.

Two sections carry most of the credibility and are the ones usually skipped:

- **The caveat, near the top.** What this does NOT do, and where it will mislead you.
  A README that only sells is one nobody trusts the second time.
- **Limitations, stated before the user finds them.** This buys more trust than any
  feature list.

If the project has claims worth proving, add a **Verified properties** section: each
claim paired with the command that reproduces it. If you cannot name a command that
proves a claim, do not make the claim.

Override this template freely if the user has their own, or if the project genuinely
does not fit — a 200-line CLI does not need an architecture diagram. Do not keep empty
headings; delete what does not apply.

**Mermaid diagrams:** never put backticks inside node labels — mermaid parses them as
markdown-string syntax and the diagram fails to render entirely. Avoid `A & B --> C`
chaining. Verify rendering before committing.

## When the project already exists

If there's a spec but the user is starting a *new piece of work*, don't bootstrap —
just write the next spec (`002-`, `003-`…) and check whether the existing config still
fits. Adding a UI? That's when `senior-frontend` and `senior-uiux` get switched on.

## Ending

Finish by telling the user exactly what to do next, in one line:

```
Config and spec 001 are ready. Read .audit/specs/001-<slug>.md — if it matches what
you meant, say "build it". If not, tell me what's wrong.
```

Never end a bootstrap without a clear next action. Run `make where` if unsure what it is.
