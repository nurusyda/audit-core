#!/usr/bin/env python3
"""
validate.py — audit-core checks itself.

Run this in audit-core's own CI. A dangling adapter_key or a rubric path that points at
nothing degrades silently into a SKIP, which looks like a pass in a busy log. That is
precisely the kind of quiet coverage loss this whole system exists to prevent, so it is
checked mechanically rather than by discipline.

    python runner/validate.py
"""

import json
import re
import sys
from pathlib import Path

import yaml

CORE = Path(__file__).resolve().parent.parent
errors, warnings = [], []


def load(p):
    return yaml.safe_load(p.read_text()) or {}


controls, ids = {}, set()
for f in sorted((CORE / "controls").glob("*.yaml")):
    for c in load(f) or []:
        cid = c.get("id")
        if not cid or not re.match(r"^CTL-\d{4}$", cid):
            errors.append(f"{f.name}: bad or missing id: {cid!r}")
            continue
        if cid in ids:
            errors.append(f"{f.name}: duplicate id {cid}")
        ids.add(cid)
        controls[cid] = (c, f.name)

# --- schema conformance -----------------------------------------------------
schema = json.loads((CORE / "schema" / "control.schema.json").read_text())
allowed = set(schema["properties"])
required = set(schema["required"])

for cid, (c, fn) in controls.items():
    missing = required - set(c)
    if missing:
        errors.append(f"{cid} ({fn}): missing required field(s) {sorted(missing)}")
    extra = set(c) - allowed
    if extra:
        errors.append(f"{cid} ({fn}): unknown field(s) {sorted(extra)}")
    for field, key in (("domain", "domain"), ("tier", "tier"), ("severity", "severity")):
        enum = schema["properties"][key].get("enum")
        if enum and c.get(field) and c[field] not in enum:
            errors.append(f"{cid}: {field}={c[field]!r} not in {enum}")
    if not c.get("why"):
        warnings.append(f"{cid}: no 'why' — findings will be unexplainable to a reviewer")
    if c.get("tier") == "tier3" and c.get("blocking") is True:
        errors.append(f"{cid}: tier3 must never block. Remove blocking:true.")

# --- adapter bindings -------------------------------------------------------
adapters = {f.stem: load(f) for f in (CORE / "adapters").glob("*.yaml")}
needed = {(c["detect"]["adapter_key"], cid)
          for cid, (c, _) in controls.items()
          if (c.get("detect") or {}).get("adapter_key")}

for key, cid in sorted(needed):
    bound = [n for n, a in adapters.items() if key in (a.get("commands") or {})]
    if not bound:
        errors.append(f"{cid}: adapter_key '{key}' is bound in NO adapter — "
                      f"this control can never run")
    else:
        # The generic fallback is intentionally sparse; do not warn about it.
        unbound = [n for n in adapters
                   if n not in bound and not adapters[n].get('fallback')]
        if unbound:
            warnings.append(f"adapter_key '{key}' ({cid}) unbound in: {', '.join(sorted(unbound))} "
                            f"— will report SKIPPED there")

# --- rubric paths -----------------------------------------------------------
for cid, (c, _) in controls.items():
    det = c.get("detect") or {}
    for field in ("rubric", "remediation"):
        val = det.get(field) or c.get(field)
        if val and not val.startswith("http") and not (CORE / val).exists():
            errors.append(f"{cid}: {field} path does not exist: {val}")
    if c.get("tier") == "tier3" and c.get("type") != "attestation" and not det.get("rubric"):
        warnings.append(f"{cid}: tier3 with no rubric — reviewer has no criteria")

# --- framework references ---------------------------------------------------
fw = load(CORE / "mappings" / "frameworks.yaml")
for name, d in fw.items():
    refs = set(d.get("controls") or [])
    for group in ("control_map", "criteria_map", "requirement_map",
                  "article_map", "safeguard_map", "technique_map"):
        for v in (d.get(group) or {}).values():
            refs.update(v)
    for r in sorted(refs - ids):
        errors.append(f"framework '{name}' references unknown control {r}")
    if d.get("extends") and d["extends"] not in fw:
        errors.append(f"framework '{name}' extends unknown '{d['extends']}'")

# --- skills own real controls -----------------------------------------------
skill_dirs = {p.name for p in (CORE / "skills").iterdir() if p.is_dir()}
owners = {c.get("owner_skill") for c, _ in controls.values()}
for o in sorted(owners - skill_dirs):
    errors.append(f"control owner_skill '{o}' has no skills/{o}/SKILL.md")
for s in sorted(skill_dirs - owners):
    # Workflow skills legitimately own no controls; they declare it explicitly.
    md = (CORE / "skills" / s / "SKILL.md")
    if md.exists() and "owns_controls: none" in md.read_text():
        continue
    warnings.append(f"skill '{s}' owns no controls — enabling it does nothing")
for s in sorted(skill_dirs):
    if not (CORE / "skills" / s / "SKILL.md").exists():
        errors.append(f"skills/{s}/ has no SKILL.md")

# --- report -----------------------------------------------------------------
print(f"audit-core self-validation\n"
      f"  {len(controls)} controls · {len(adapters)} adapters · "
      f"{len(skill_dirs)} skills · {len(fw)} frameworks\n")

for w in warnings:
    print(f"  WARN  {w}")
if warnings:
    print()
for e in errors:
    print(f"  ERROR {e}")

if errors:
    print(f"\nFAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1)
print(f"PASSED ({len(warnings)} warning(s))")
sys.exit(0)
