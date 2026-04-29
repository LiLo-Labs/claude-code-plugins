#!/usr/bin/env python3
"""Stage 4.5 — Deterministic verification that polish didn't silently drop content.

For every polished `processed/<name>.md`, diffs against the pre-polish snapshot
at `processed/.snapshot/<name>.md` (written by cleanup.py) and runs several
content-preservation checks:

  1. Word / line / character counts (informational ratio).
  2. Identifier preservation: RITM/REQ/DMND/SFSTRY/SFFEAT/SFEPIC/PRJ/TASK/QUA-
     numbers, email addresses, URLs, dollar amounts, ISO & US dates, port
     numbers. Every identifier in the snapshot must appear in the polished
     file; any miss is a CRITICAL flag.
  3. Number preservation: every 3+ digit number in snapshot → must appear in
     polished file; threshold 95%.
  4. Named-entity preservation: 2-to-4-word TitleCase sequences; threshold 90%.
  5. 5-gram shingle Jaccard similarity: should stay ≥ 0.25 (polish rearranges
     sentences but preserves most substrings).

Emits `_verify.md` (appended to `_summary.md` by chunk.py) with:
  - Per-file stats table.
  - Flagged files with specific missing items.
  - A spot-check-recommendation list.

Usage:
    python3 verify.py --dir <processed-folder>
"""
from __future__ import annotations
import argparse, pathlib, re, collections

# Thresholds — tuned to flag real loss without false alarming on reordering.
THRESHOLDS = {
    "identifier_coverage_min": 1.00,   # CRITICAL if <
    "number_coverage_min":     0.95,
    "entity_coverage_min":     0.90,
    "word_ratio_min":          0.70,   # polished shouldn't have <70% of original words
    "shingle_jaccard_min":     0.25,
}

# ─── Extractors ─────────────────────────────────────────────────────────────
ID_PATTERNS = [
    (r'\bRITM\d+\b',                        "servicenow-item"),
    (r'\bREQ\d+\b',                         "servicenow-request"),
    (r'\bDMND\d+\b',                        "servicenow-demand"),
    (r'\bSFSTRY\d+\b',                      "safe-story"),
    (r'\bSFFEAT\d+\b',                      "safe-feature"),
    (r'\bSFEPIC\d+\b',                      "safe-epic"),
    (r'\bPRJ\d+\b',                         "project-id"),
    (r'\bTASK\d+\b',                        "task-id"),
    (r'\bQUA-\d+\b',                        "treatment-id"),
    (r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b',       "email"),
    (r'https?://\S+',                       "url"),
    (r'\$[\d,]+(?:\.\d+)?[KMB]?\b',         "money"),
    (r'\b\d{4}-\d{2}-\d{2}\b',              "iso-date"),
    (r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',        "us-date"),
    (r'\b(?:port\s+)?\d{2,5}(?=\s*[:/\)]|\s*$|\s+port)', "port-number"),   # loose; we'll dedupe
]

NUMBER_PATTERN = re.compile(r'\b\d{3,}\b')                       # 3+ digit standalone numbers
ENTITY_PATTERN = re.compile(r'\b(?:[A-Z][a-z]+\s+){1,3}[A-Z][a-z]+\b')  # 2-4 TitleCase words


def extract_identifiers(text: str) -> set[str]:
    out: set[str] = set()
    for pat, _kind in ID_PATTERNS:
        out.update(m.group(0) for m in re.finditer(pat, text))
    return out


def extract_numbers(text: str) -> set[str]:
    return set(NUMBER_PATTERN.findall(text))


def extract_entities(text: str) -> set[str]:
    return set(ENTITY_PATTERN.findall(text))


def shingles(text: str, k: int = 5) -> set[str]:
    words = text.split()
    return {" ".join(words[i:i+k]).lower() for i in range(len(words) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b: return 1.0
    if not a or not b:  return 0.0
    return len(a & b) / len(a | b)


def strip_chunk_markers(text: str) -> str:
    """Remove `<!-- chunk:start/end -->` comments so they don't count as
    content-change."""
    text = re.sub(r"^<!-- chunk:(start|end)[^>]*-->\n", "", text, flags=re.MULTILINE)
    return text


# ─── Per-file diff ──────────────────────────────────────────────────────────
FRAGMENT_QUANTIFIERS = re.compile(
    r'^\*\*A:\*\*\s*(Less than|Greater than|More than|Fewer than|At least|Up to|Over|Under|At most|Approximately|Between \S+ and|From \S+ to)\s*$',
    re.MULTILINE
)
FRAGMENT_DANGLING = re.compile(
    r'^\*\*A:\*\*\s+.*\b(of|to|for|with|by|from|the|a|an|and|or|but)\s*$',
    re.MULTILINE
)
FRAGMENT_CURRENCY = re.compile(
    r'^\*\*A:\*\*\s*(\$|USD|port|page|section|item|chapter)\s*$',
    re.MULTILINE | re.IGNORECASE
)
FRAGMENT_EMPTY_NUMERIC_Q = re.compile(
    # Q asks for a number/date/percentage/TIN; A is an echoed-context string ending in "| Unknown" or is empty
    r'\*\*Q[^*]+\*\*\s*—\s*(?:[^\n]*(?:Tax\s*ID|number of|how many|percentage|what\s*date|Enter)[^\n]*)\n'
    r'\*\*A:\*\*\s*(?:Quantivly[^\n]*\|\s*Unknown|\(not answered\))\s*$',
    re.MULTILINE | re.IGNORECASE
)


def find_fragments(text: str) -> list[tuple[str, str]]:
    """Return [(kind, snippet)] for fragment-style defects in the polished text."""
    out = []
    for m in FRAGMENT_QUANTIFIERS.finditer(text):
        out.append(("quantifier-no-number", m.group(0)))
    for m in FRAGMENT_DANGLING.finditer(text):
        out.append(("dangling-preposition", m.group(0)))
    for m in FRAGMENT_CURRENCY.finditer(text):
        out.append(("currency-no-amount", m.group(0)))
    for m in FRAGMENT_EMPTY_NUMERIC_Q.finditer(text):
        out.append(("numeric-question-echo-answer", m.group(0)[:200]))
    return out


def verify_file(snapshot_text: str, polished_text: str) -> dict:
    snap = strip_chunk_markers(snapshot_text)
    pol  = strip_chunk_markers(polished_text)

    snap_ids  = extract_identifiers(snap)
    pol_ids   = extract_identifiers(pol)
    missing_ids = snap_ids - pol_ids

    snap_nums = extract_numbers(snap)
    pol_nums  = extract_numbers(pol)
    missing_nums = snap_nums - pol_nums

    snap_ents = extract_entities(snap)
    pol_ents  = extract_entities(pol)
    missing_ents = snap_ents - pol_ents

    snap_shingles = shingles(snap)
    pol_shingles  = shingles(pol)
    jacc = jaccard(snap_shingles, pol_shingles)

    snap_words = len(snap.split())
    pol_words  = len(pol.split())
    word_ratio = pol_words / snap_words if snap_words else 1.0

    def cov(missing: set, total: set) -> float:
        return 1.0 if not total else (len(total) - len(missing)) / len(total)

    id_cov  = cov(missing_ids,  snap_ids)
    num_cov = cov(missing_nums, snap_nums)
    ent_cov = cov(missing_ents, snap_ents)

    fragments = find_fragments(pol)

    flags = []
    if id_cov  < THRESHOLDS["identifier_coverage_min"]:
        flags.append(("CRITICAL", f"identifier coverage {id_cov:.0%}"))
    if num_cov < THRESHOLDS["number_coverage_min"]:
        flags.append(("WARN", f"number coverage {num_cov:.0%}"))
    if ent_cov < THRESHOLDS["entity_coverage_min"]:
        flags.append(("WARN", f"named-entity coverage {ent_cov:.0%}"))
    if word_ratio < THRESHOLDS["word_ratio_min"]:
        flags.append(("WARN", f"word ratio {word_ratio:.0%}"))
    if jacc < THRESHOLDS["shingle_jaccard_min"]:
        flags.append(("WARN", f"5-gram Jaccard {jacc:.2f}"))
    if fragments:
        flags.append(("CRITICAL", f"{len(fragments)} sentence-fragment(s) detected"))

    return {
        "snap_words": snap_words, "pol_words": pol_words,
        "word_ratio": word_ratio,
        "id_count_before": len(snap_ids), "id_missing": sorted(missing_ids),
        "id_coverage": id_cov,
        "num_count_before": len(snap_nums), "num_missing_count": len(missing_nums),
        "num_coverage": num_cov,
        "ent_count_before": len(snap_ents), "ent_missing_count": len(missing_ents),
        "ent_coverage": ent_cov,
        "jaccard": jacc,
        "fragments": fragments,
        "flags": flags,
    }


# ─── Driver ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="Processed folder (with .snapshot/)")
    ap.add_argument("--snapshot-dir", default=None,
                    help="Override snapshot folder (default: <dir>/.snapshot)")
    args = ap.parse_args()

    root = pathlib.Path(args.dir).expanduser().resolve()
    snap_root = pathlib.Path(args.snapshot_dir).expanduser().resolve() if args.snapshot_dir else root / ".snapshot"
    if not snap_root.is_dir():
        raise SystemExit(f"No snapshot at {snap_root}. Run cleanup.py first (or pass --snapshot-dir).")

    results = {}
    for md in sorted(root.glob("*.md")):
        if md.name.startswith("_"): continue
        snap = snap_root / md.name
        if not snap.exists():
            print(f"WARN: no snapshot for {md.name}; skipping")
            continue
        r = verify_file(snap.read_text(), md.read_text())
        results[md.name] = r
        lab = "CRIT " if any(f[0] == "CRITICAL" for f in r["flags"]) else ("WARN " if r["flags"] else "ok   ")
        print(f"[{lab}] {md.name}: ids {r['id_coverage']:.0%} · nums {r['num_coverage']:.0%} · "
              f"ents {r['ent_coverage']:.0%} · words {r['word_ratio']:.0%} · jacc {r['jaccard']:.2f}")

    # Write _verify.md — chunk.py will fold it into _summary.md at the end.
    lines = ["# Verification report", "",
             "Deterministic diff between pre-polish snapshot and final polished "
             "markdown. Counts identifier / number / named-entity coverage plus a "
             "5-gram Jaccard of the two texts.", ""]
    lines.append("## Thresholds")
    lines.append("")
    for k, v in THRESHOLDS.items():
        lines.append(f"- `{k}` = {v}")
    lines.append("")

    crit = [n for n, r in results.items() if any(f[0] == "CRITICAL" for f in r["flags"])]
    warn = [n for n, r in results.items() if any(f[0] == "WARN"     for f in r["flags"]) and n not in crit]
    clean = [n for n in results if n not in crit and n not in warn]

    lines.extend(["## Summary", "",
                  f"- Files checked: **{len(results)}**",
                  f"- Passed all thresholds: **{len(clean)}**",
                  f"- **WARN**: {len(warn)}",
                  f"- **CRITICAL**: {len(crit)}",
                  ""])

    if crit or warn:
        lines.append("## Flagged files")
        lines.append("")
        lines.append("| File | Level | Issues |")
        lines.append("|------|-------|--------|")
        for n in crit + warn:
            r = results[n]
            level = "CRITICAL" if n in crit else "WARN"
            issues = "; ".join(f"{lvl}: {msg}" for lvl, msg in r["flags"])
            lines.append(f"| {n} | {level} | {issues} |")
        lines.append("")
        lines.append("### Spot-check recommendation")
        lines.append("")
        lines.append("For each flagged file above, read both")
        lines.append("  `processed/.snapshot/<name>` and `processed/<name>`,")
        lines.append("and visually confirm that nothing substantive is missing.")
        lines.append("You can also dispatch a verifier sub-agent with a diff of the two files and ask whether any semantic content was lost.")
        lines.append("")

    lines.append("## Per-file detail")
    lines.append("")
    lines.append("| File | Before→After words | Word ratio | ID cov | Num cov | Ent cov | Jaccard |")
    lines.append("|------|--------------------|------------|--------|---------|---------|---------|")
    for n, r in sorted(results.items()):
        lines.append(
            f"| {n} | {r['snap_words']}→{r['pol_words']} | {r['word_ratio']:.0%} | "
            f"{r['id_coverage']:.0%} | {r['num_coverage']:.0%} | {r['ent_coverage']:.0%} | "
            f"{r['jaccard']:.2f} |"
        )
    lines.append("")

    # Per-flagged-file missing-identifier lists (so you can grep what's gone).
    if crit:
        lines.append("## Missing identifiers (CRITICAL only)")
        lines.append("")
        for n in crit:
            if not results[n]["id_missing"]: continue
            lines.append(f"### {n}")
            lines.append("")
            for mid in results[n]["id_missing"]:
                lines.append(f"- `{mid}`")
            lines.append("")

    # Fragment detections — these fire on the polished text alone, no snapshot needed.
    frag_files = [(n, r) for n, r in results.items() if r.get("fragments")]
    if frag_files:
        lines.append("## Sentence fragments / incomplete answers detected")
        lines.append("")
        lines.append("These polished answers look truncated or missing a value. "
                     "Most likely the extractor dropped a bare-number or bare-token "
                     "line that the agent couldn't reconstruct. Look up the real "
                     "answer in the source document and patch the file.")
        lines.append("")
        for n, r in frag_files:
            lines.append(f"### {n}")
            lines.append("")
            for kind, snippet in r["fragments"]:
                lines.append(f"- **{kind}**")
                lines.append(f"  ```")
                lines.append(f"  {snippet}")
                lines.append(f"  ```")
            lines.append("")

    (root / "_verify.md").write_text("\n".join(lines) + "\n")
    print(f"\nWrote {root}/_verify.md — {len(crit)} CRITICAL, {len(warn)} WARN, {len(clean)} clean")


if __name__ == "__main__":
    main()
