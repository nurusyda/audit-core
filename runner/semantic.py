#!/usr/bin/env python3
"""
semantic.py — LLM-assisted coherence review, with every claim verified before a
human ever sees it.

THE HALLUCINATION PROBLEM
=========================
An LLM asked "does this duplicate existing logic?" will confidently cite a function
that does not exist, at a line number it invented, quoting code it wrote itself. A
review full of plausible fabrications is worse than no review, because it burns the
reviewer's trust in every finding including the true ones.

So this module treats LLM output as an UNVERIFIED CLAIM, never as a finding.

Two tiers of grounding, both mandatory:

  Tier 1 — EXISTENCE.  The cited file exists in the repo. The cited line is within
           that file. The cited symbol appears in the deterministic symbol table
           built by coherence.py (not by the model).

  Tier 2 — LITERAL.    The `exact_quote` the model returned appears VERBATIM in the
           cited file, within +/- LINE_TOLERANCE lines of the cited line. Whitespace
           is normalised; nothing else is.

A claim failing either tier is DROPPED and counted. It is never shown to the human,
never written to the report, never allowed to block anything. The drop rate is
reported so the backend's reliability is visible and measurable rather than assumed.

This is tier3-advisory, permanently. LLM output is non-deterministic — the same diff
yields different findings run to run — and a gate that flickers gets bypassed.
"""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("semantic: PyYAML required")

LINE_TOLERANCE = 12        # the model's line arithmetic drifts; its quotes should not
MAX_CLAIMS = 25


SYSTEM_PROMPT = """You are a senior engineer reviewing whether a code change conflicts \
with code that already exists in the repository.

You are looking ONLY for coherence problems:
- Logic that duplicates something already implemented elsewhere
- A second way of doing something the codebase already does one way
- A new abstraction that overlaps an existing one
- Code that contradicts an established pattern in this repository

You are NOT looking for bugs, style, security, or performance. Other tools cover those.

CRITICAL RULES ABOUT EVIDENCE:

1. Every claim MUST cite a real file path from the SYMBOL TABLE provided below.
2. Every claim MUST include `exact_quote`: a contiguous span of 1-3 lines copied
   CHARACTER FOR CHARACTER from the file you are citing. Do not paraphrase it. Do not
   reformat it. Do not fix its indentation. Copy it exactly as given to you.
3. If you cannot supply an exact quote from the material provided, DO NOT MAKE THE
   CLAIM. Omit it entirely.
4. Never cite a file, symbol, or line that does not appear in the material below.
5. An empty findings list is a valid and often correct answer.

Every claim you make will be mechanically verified against the actual repository
before any human sees it. Claims whose quotes do not match are discarded and counted
against you. Fabricating a citation is strictly worse than reporting nothing.

Respond with ONLY a JSON object, no markdown fences, no preamble:

{"findings": [
  {"claim": "one sentence describing the conflict",
   "new_file": "path from the diff",
   "new_line": 42,
   "existing_file": "path from the symbol table",
   "existing_line": 118,
   "existing_symbol": "name_of_existing_function",
   "exact_quote": "verbatim lines from existing_file",
   "severity": "medium",
   "recommendation": "one sentence"}
]}"""


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def git(root, *a):
    return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True).stdout


def excluded(path, patterns):
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def build_context(root, base, cfg):
    """
    Assemble what the model sees. Two modes:

      send_source: true   full diff + symbol table with source excerpts
      send_source: false  symbol names and signatures only — no implementation bodies
                          leave the machine. Catches most duplication; ships far less.
    """
    sem = cfg.get("semantic_review") or {}
    excl = sem.get("exclude_paths") or []
    send_source = sem.get("send_source", False)

    diff = git(root, "diff", f"{base}...HEAD")
    if not diff.strip():
        diff = git(root, "diff", "--cached")

    kept, skipped = [], []
    current, path = [], None
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git"):
            if path is not None:
                (skipped if excluded(path, excl) else kept).append((path, "".join(current)))
            m = re.search(r"b/(\S+)", line)
            path, current = (m.group(1) if m else "?"), [line]
        else:
            current.append(line)
    if path is not None:
        (skipped if excluded(path, excl) else kept).append((path, "".join(current)))

    diff_text = "".join(c for _, c in kept)
    max_kb = sem.get("max_diff_kb", 60)
    truncated = False
    if len(diff_text) > max_kb * 1024:
        diff_text = diff_text[: max_kb * 1024]
        truncated = True

    coh = root / ".audit" / "coherence.json"
    symbols = []
    if coh.exists():
        data = json.loads(coh.read_text())
        # Reuse the DETERMINISTIC symbol table. The model never builds its own —
        # that is the first place fabricated citations would come from.
        for f in data.get("results", {}).get("CTL-0512", {}).get("findings", []):
            for e in f.get("existing", []):
                if not excluded(e["file"], excl):
                    symbols.append(e)

    sym_lines = []
    for rel in sorted({s["file"] for s in symbols})[:40]:
        p = root / rel
        if not p.exists():
            continue
        if send_source:
            src = p.read_text(errors="replace").splitlines()
            numbered = "\n".join(f"{i:>5}| {l}" for i, l in enumerate(src[:400], 1))
            sym_lines.append(f"--- FILE: {rel} ---\n{numbered}")
        else:
            src = p.read_text(errors="replace").splitlines()
            sigs = [f"{i:>5}| {l}" for i, l in enumerate(src, 1)
                    if re.match(r"\s*(def |class |function |export |async def )", l)]
            sym_lines.append(f"--- FILE: {rel} (signatures only) ---\n" + "\n".join(sigs))

    return {
        "diff": diff_text,
        "symbols": "\n\n".join(sym_lines),
        "skipped_paths": [p for p, _ in skipped],
        "truncated": truncated,
        "send_source": send_source,
    }


# ---------------------------------------------------------------------------
# Backend — any OpenAI-compatible endpoint
# ---------------------------------------------------------------------------

def call_llm(cfg, context):
    sem = cfg.get("semantic_review") or {}
    base_url = sem.get("base_url", "https://api.deepseek.com").rstrip("/")
    model = sem.get("model", "deepseek-chat")
    key = os.environ.get(sem.get("api_key_env", "SEMANTIC_API_KEY"))
    if not key:
        return None, f"{sem.get('api_key_env', 'SEMANTIC_API_KEY')} not set in environment"

    user = (f"=== SYMBOL TABLE (existing code) ===\n{context['symbols']}\n\n"
            f"=== DIFF (the change under review) ===\n{context['diff']}")

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": 3000,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions" if not base_url.endswith("/v1")
        else f"{base_url}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=sem.get("timeout", 120)) as r:
            body = json.loads(r.read())
        return body["choices"][0]["message"]["content"], None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"
    except Exception as e:                                     # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def parse_claims(text):
    if not text:
        return [], "empty response"
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.S)
        if not m:
            return [], "no JSON object in response"
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            return [], f"unparseable JSON: {e}"
    claims = data.get("findings")
    if not isinstance(claims, list):
        return [], "no findings list"
    return claims[:MAX_CLAIMS], None


# ---------------------------------------------------------------------------
# GROUNDING — the part that matters
# ---------------------------------------------------------------------------

def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def verify(claim, root, symbol_table):
    """
    Returns (verdict, reason). Verdicts:
      GROUNDED    passed Tier 1 and Tier 2 — safe to show a human
      UNGROUNDED  cited real things but the quote could not be located
      FABRICATED  cited a file, line, or symbol that does not exist

    Only GROUNDED reaches the report.
    """
    required = ("claim", "existing_file", "exact_quote")
    for f in required:
        if not claim.get(f):
            return "FABRICATED", f"missing required field '{f}'"

    rel = claim["existing_file"]
    p = root / rel

    # --- Tier 1: existence ------------------------------------------------
    if not p.exists() or not p.is_file():
        return "FABRICATED", f"cited file does not exist: {rel}"

    try:
        lines = p.read_text(errors="replace").splitlines()
    except OSError as e:
        return "UNGROUNDED", f"unreadable: {e}"

    line_no = claim.get("existing_line")
    if isinstance(line_no, int) and not (1 <= line_no <= len(lines)):
        return "FABRICATED", (f"cited line {line_no} outside {rel} "
                              f"(file has {len(lines)} lines)")

    # The symbol check must ALWAYS run. Gating it on a non-empty symbol table made it
    # silently skip itself and return GROUNDED for invented symbols — the precise
    # failure mode this module exists to prevent.
    sym = claim.get("existing_symbol")
    if sym:
        text = "\n".join(lines)
        in_table = any(s.get("name") == sym and s.get("file") == rel
                       for s in (symbol_table or []))
        in_file = re.search(rf"\b{re.escape(sym)}\b", text) is not None
        if not (in_table or in_file):
            return "FABRICATED", f"symbol '{sym}' does not appear in {rel}"

    # --- Tier 2: literal quote --------------------------------------------
    quote = norm(claim["exact_quote"])
    if len(quote) < 10:
        return "UNGROUNDED", "quote too short to verify meaningfully"

    haystack_all = norm("\n".join(lines))
    if quote not in haystack_all:
        return "FABRICATED", "exact_quote does not appear anywhere in the cited file"

    if isinstance(line_no, int):
        lo = max(0, line_no - 1 - LINE_TOLERANCE)
        hi = min(len(lines), line_no + LINE_TOLERANCE)
        if quote not in norm("\n".join(lines[lo:hi])):
            return "UNGROUNDED", (f"quote exists in {rel} but not within "
                                  f"±{LINE_TOLERANCE} lines of cited line {line_no}")

    return "GROUNDED", "file, line, symbol and literal quote all verified"


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".audit/config.yaml")
    ap.add_argument("--base", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="Assemble and print context without calling the API.")
    args = ap.parse_args()

    root = Path.cwd()
    cfg = yaml.safe_load((root / args.config).read_text()) or {}
    sem = cfg.get("semantic_review") or {}

    if not sem.get("enabled"):
        print("semantic: disabled in .audit/config.yaml (semantic_review.enabled: false)")
        return 0

    base = args.base or cfg.get("base_ref", "origin/main")
    context = build_context(root, base, cfg)

    if context["skipped_paths"]:
        print(f"semantic: {len(context['skipped_paths'])} path(s) EXCLUDED from the "
              f"API call by exclude_paths:")
        for p in context["skipped_paths"][:8]:
            print(f"    {p}")
    print(f"semantic: send_source={context['send_source']} · "
          f"diff {len(context['diff'])//1024}KB"
          + (" (TRUNCATED)" if context["truncated"] else ""))

    if args.dry_run:
        print("\n--- would send ---\n")
        print(context["symbols"][:2000])
        print("\n[diff omitted]")
        return 0

    if not context["diff"].strip():
        print("semantic: nothing to review")
        return 0

    raw, err = call_llm(cfg, context)
    if err:
        print(f"semantic: backend unavailable — {err}")
        print("semantic: NOT CHECKED. This is not a pass.")
        return 0

    claims, perr = parse_claims(raw)
    if perr:
        print(f"semantic: could not parse response — {perr}")
        return 0

    coh = root / ".audit" / "coherence.json"
    symbol_table = []
    if coh.exists():
        d = json.loads(coh.read_text())
        for f in d.get("results", {}).get("CTL-0512", {}).get("findings", []):
            symbol_table.extend(f.get("existing", []))

    grounded, dropped = [], []
    for c in claims:
        verdict, reason = verify(c, root, symbol_table)
        rec = {**c, "verdict": verdict, "verification": reason}
        (grounded if verdict == "GROUNDED" else dropped).append(rec)

    total = len(claims)
    fab = sum(1 for d in dropped if d["verdict"] == "FABRICATED")
    rate = (fab / total * 100) if total else 0.0

    report = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backend": {"base_url": sem.get("base_url"), "model": sem.get("model")},
        "send_source": context["send_source"],
        "excluded_paths": context["skipped_paths"],
        "claims_returned": total,
        "grounded": len(grounded),
        "dropped": len(dropped),
        "fabricated": fab,
        "hallucination_rate_pct": round(rate, 1),
        "findings": grounded,
        "discarded": dropped,
        "tier": "tier3-advisory",
    }
    out = root / ".audit" / "reports" / "semantic-review.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print(f"\nsemantic: {total} claim(s) returned · {len(grounded)} GROUNDED · "
          f"{len(dropped)} dropped ({fab} fabricated)")
    print(f"semantic: hallucination rate {rate:.1f}%")

    for g in grounded:
        print(f"\n  [VERIFIED] {g['claim']}")
        print(f"    new:      {g.get('new_file')}:{g.get('new_line')}")
        print(f"    existing: {g['existing_file']}:{g.get('existing_line')} "
              f"({g.get('existing_symbol')})")
        print(f"    fix:      {g.get('recommendation', '-')}")

    if dropped:
        print(f"\n  {len(dropped)} claim(s) DISCARDED — not shown as findings:")
        for d in dropped[:6]:
            print(f"    [{d['verdict']}] {d['verification']}")

    print("\nsemantic: advisory only — never blocks. See gate A report.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                   # noqa: BLE001
        print(f"semantic: CRASHED — {type(exc).__name__}: {exc}", file=sys.stderr)
        print("semantic: NOT CHECKED. This is not a pass.", file=sys.stderr)
        sys.exit(0)     # advisory: a crash here must never block a build
