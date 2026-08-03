# audit-core

The engine. Controls, specialist skills, adapters, and the gate runner.

**This repo is never copied into a project.** Projects depend on it by pinned version.
That is deliberate: copies fork, and forked controls mean six divergent security systems
and no idea which one is current.

## Layout

```
controls/      Control definitions. The content.
mappings/      Frameworks as filters over controls (OWASP, SOC2, PCI, GDPR, NIST, MITRE…)
adapters/      Per-stack tool bindings. Controls never name a language.
skills/        Specialist SKILL.md files — the senior engineers.
rubrics/       Judgment criteria for tier3 controls.
runner/        audit.py (gate B) · report.py (gate A) · gates.py (enforcement)
templates/     spec.md
scripts/       install-hooks.sh
schema/        control.schema.json
```

## The three tiers

| Tier | Verified by | Blocks? |
|---|---|---|
| tier1 | A tool returns pass/fail | yes |
| tier2 | A number vs a budget, ratcheted | yes |
| tier3 | Judgment against a rubric | **never** |

Tier3 never blocks. A gate that fails on a judgment call becomes flaky, and a flaky gate
gets bypassed within two weeks — at which point you have no gate at all.

## The two gates

```
build → GATE B (audit, agent fixes and re-runs, max 3 rounds)
      → GATE A (human reviews the final green state)
      → changes requested? → back to B → A shows only the DELTA
      → commit (needs B) → push (needs B + A)
```

B runs before A on purpose. Reviewing a build that is about to change five more times is
how review fatigue starts, and review fatigue turns your best gate into a rubber stamp.

## Adding a control

1. Add it to a file in `controls/`, with a `why` a non-specialist can read.
2. Bind any `adapter_key` in every adapter (`SKIP` where inapplicable).
3. Map it into `mappings/frameworks.yaml` if a framework needs it.
4. Seed it as **non-blocking** on real projects first. Watch the noise for two weeks.
5. Promote to blocking only once it fires accurately.

## Adding a stack

One file in `adapters/`. Controls do not change. That is the whole point of keying on CWE.

## Maintenance rules that keep this alive

- **Pin tool versions.** An unpinned semgrep means a vendor rule update breaks main on an
  unrelated PR, and the team learns to use `--no-verify`.
- **Track precision per control.** `.audit/reports/control-stats.jsonl` accumulates
  fired/fixed/waived. A control waived 80% of the time is noise — delete it.
  Gate credibility is the entire asset; one noisy check teaches people to distrust all of them.
- **Log tier3 overrides.** Disagreeing with a judgment finding is evidence the rubric is
  wrong. Rubrics are prose and rot fastest.
- **Waivers expire.** Enforced by the runner.
- **Watch bypass count.** Rising `--no-verify` is the leading indicator this system is
  dying, and it shows up long before anyone says so.
- **Dogfood.** This repo runs its own gates. If it is too annoying to use on itself, it is
  too annoying.

## Honest limits

- Automated a11y testing catches ~35% of real WCAG failures. The rest is tier3.
- SOC 2 / ISO / PCI are audits of your organisation. This produces evidence for them; it
  does not satisfy them. Do not quote a compliance percentage from this tool.
- MITRE ATT&CK is mapped at the mitigation level. Detection coverage lives in your SIEM.
- Every scanner has false negatives. A green run means "nothing known was found."

## Versioning

SemVer. **Adding a blocking control is a MAJOR bump** — it can break a downstream build.
