#!/usr/bin/env python3
"""Stage 5 — Inject inline HTML chunk-boundary markers and emit JSON manifests.

For every polished markdown in `manipulated/` (excluding `_`-prefixed files),
identifies atomic semantic blocks (qa, risk, image, table, metadata, heading,
prose, bullet_list), wraps them in `<!-- chunk:start/end -->` HTML comments,
and writes per-file `<name>.chunks.json` into `manipulated/_chunks/` plus an
aggregate `manipulated/_chunk_index.json`.

Also consolidates per-file polish reports from `_polish_reports/` into the
top-level `_summary.md` and deletes the reports folder. Result: the processed
folder contains only the polished `.md` files, `embedded_images/`, and a
single `_summary.md`.

Usage:
    python3 chunk.py --dir <processed-folder>
"""
from __future__ import annotations
import argparse, collections, json, pathlib, re

H2 = re.compile(r"^##\s+(.+?)\s*$")
H3 = re.compile(r"^###\s+(.+?)\s*$")
Q_LINE  = re.compile(r"^\*\*Q\s+(\S+)\*\*\s*")
A_LINE  = re.compile(r"^\*\*A:\*\*\s*")
RISK_HEADER = re.compile(r"^\s*\*\*RISK\*\*", re.IGNORECASE)
IMAGE_LINE  = re.compile(r"^\s*\*\*\[Image\s*—")
TABLE_SEP   = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")
HAS_PIPE    = re.compile(r"^\s*\|.*\|\s*$")
BULLET      = re.compile(r"^\s*[-*]\s+")


def estimate_tokens(s: str) -> int:
    return int(len(s.split()) * 1.3) + 1


def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s.lower()).strip("-")
    return s[:50] or "section"


def parse_file(lines):
    chunks, i, n = [], 0, len(lines)
    h2, h3 = None, None
    while i < n:
        line = lines[i]; s = line.rstrip(); stripped = s.strip()
        if stripped == "": i += 1; continue

        m2 = H2.match(s); m3 = H3.match(s)
        if m2 or m3:
            title = (m2 or m3).group(1)
            level = "h2" if m2 else "h3"
            if level == "h2": h2 = title; h3 = None
            else: h3 = title
            start = i; i += 1
            body = []
            while i < n:
                ln = lines[i].rstrip()
                if (H2.match(ln) or H3.match(ln) or Q_LINE.match(ln)
                        or RISK_HEADER.match(ln) or IMAGE_LINE.match(ln)): break
                if HAS_PIPE.match(ln) and i+1<n and TABLE_SEP.match(lines[i+1]): break
                body.append(ln); i += 1
            text = "\n".join([s] + body).rstrip()
            chunks.append({"type":"heading","level":level,"title":title,
                           "start":start,"end":i-1,"tokens":estimate_tokens(text),
                           "parent":h2 if level=="h3" else None,"text":text})
            continue

        if Q_LINE.match(s):
            qnum = Q_LINE.match(s).group(1)
            start = i; block = [s]; i += 1
            while i < n:
                ln = lines[i].rstrip(); st = ln.strip()
                if (Q_LINE.match(ln) or H2.match(ln) or H3.match(ln)
                        or RISK_HEADER.match(ln) or IMAGE_LINE.match(ln)): break
                if st == "" and len(block) >= 2 and block[-1].strip() != "":
                    if any(A_LINE.match(x) for x in block):
                        i += 1; break
                block.append(ln); i += 1
            text = "\n".join(block).rstrip()
            chunks.append({"type":"qa","q_id":qnum,"start":start,"end":i-1,
                           "tokens":estimate_tokens(text),"parent":h2,"sub_parent":h3,"text":text})
            continue

        if RISK_HEADER.match(s):
            start = i; block = [s]; i += 1
            while i < n:
                ln = lines[i].rstrip(); st = ln.strip()
                if (RISK_HEADER.match(ln) or Q_LINE.match(ln) or H2.match(ln)
                        or H3.match(ln) or IMAGE_LINE.match(ln)): break
                if st == "" and i+1 < n:
                    nxt = lines[i+1].strip()
                    if not BULLET.match(nxt):
                        i += 1; break
                block.append(ln); i += 1
            text = "\n".join(block).rstrip()
            chunks.append({"type":"risk","start":start,"end":i-1,
                           "tokens":estimate_tokens(text),"parent":h2,"sub_parent":h3,"text":text})
            continue

        if IMAGE_LINE.match(s):
            start = i; block = [s]; i += 1
            while i < n:
                ln = lines[i].rstrip(); st = ln.strip()
                if st == "": i += 1; break
                if (Q_LINE.match(ln) or RISK_HEADER.match(ln)
                        or H2.match(ln) or H3.match(ln) or IMAGE_LINE.match(ln)): break
                block.append(ln); i += 1
            text = "\n".join(block).rstrip()
            chunks.append({"type":"image","start":start,"end":i-1,
                           "tokens":estimate_tokens(text),"parent":h2,"sub_parent":h3,"text":text})
            continue

        if HAS_PIPE.match(s) and i+1 < n and TABLE_SEP.match(lines[i+1]):
            start = i; block = [s, lines[i+1].rstrip()]; i += 2
            while i < n and HAS_PIPE.match(lines[i].rstrip()):
                block.append(lines[i].rstrip()); i += 1
            text = "\n".join(block)
            chunks.append({"type":"table","start":start,"end":i-1,
                           "tokens":estimate_tokens(text),"parent":h2,"sub_parent":h3,"text":text})
            continue

        if BULLET.match(s):
            start = i; block = [s]; i += 1
            while i < n:
                ln = lines[i].rstrip(); st = ln.strip()
                if st == "": break
                if (Q_LINE.match(ln) or H2.match(ln) or H3.match(ln)
                        or RISK_HEADER.match(ln) or IMAGE_LINE.match(ln)): break
                if HAS_PIPE.match(ln) and i+1<n and TABLE_SEP.match(lines[i+1]): break
                block.append(ln); i += 1
            text = "\n".join(block).rstrip()
            is_metadata = (all(":**" in b for b in block[:3] if "**" in b)
                           and ("Metadata" in (h2 or "") or start < 30))
            chunks.append({"type":"metadata" if is_metadata else "bullet_list",
                           "start":start,"end":i-1,"tokens":estimate_tokens(text),
                           "parent":h2,"sub_parent":h3,"text":text})
            continue

        # prose
        start = i; block = [s]; i += 1
        while i < n:
            ln = lines[i].rstrip(); st = ln.strip()
            if st == "": break
            if (Q_LINE.match(ln) or H2.match(ln) or H3.match(ln)
                    or RISK_HEADER.match(ln) or IMAGE_LINE.match(ln) or BULLET.match(ln)): break
            if HAS_PIPE.match(ln) and i+1<n and TABLE_SEP.match(lines[i+1]): break
            block.append(ln); i += 1
        text = "\n".join(block).rstrip()
        chunks.append({"type":"prose","start":start,"end":i-1,
                       "tokens":estimate_tokens(text),"parent":h2,"sub_parent":h3,"text":text})
    return chunks


def inject_markers(lines, chunks, file_id):
    out = list(lines)
    for idx, c in enumerate(reversed(chunks)):
        if c["type"] == "qa":         cid = f"{file_id}::qa::{c['q_id']}"
        elif c["type"] == "heading":  cid = f"{file_id}::heading::{slugify(c['title'])}"
        elif c["type"] == "metadata": cid = f"{file_id}::metadata"
        else:
            cid = f"{file_id}::{c['type']}::{len(chunks)-1-idx}"
        c["id"] = cid
        parent = c.get("parent") or ""; sub = c.get("sub_parent") or ""
        start_m = (f"<!-- chunk:start id=\"{cid}\" type=\"{c['type']}\" tokens=\"{c['tokens']}\""
                   + (f" parent=\"{slugify(parent)}\"" if parent else "")
                   + (f" sub_parent=\"{slugify(sub)}\"" if sub else "") + " -->")
        end_m = f"<!-- chunk:end id=\"{cid}\" -->"
        out.insert(c["end"]+1, end_m)
        out.insert(c["start"], start_m)
    return out


def build_manifest(chunks, file_id, filename):
    return {
        "file": filename, "file_id": file_id,
        "chunk_count": len(chunks),
        "total_tokens": sum(c["tokens"] for c in chunks),
        "by_type": dict(collections.Counter(c["type"] for c in chunks)),
        "chunks": [{
            "id": c["id"], "type": c["type"],
            "start_line": c["start"]+1, "end_line": c["end"]+1,
            "tokens": c["tokens"], "parent": c.get("parent"),
            "sub_parent": c.get("sub_parent"), "title": c.get("title"),
            "q_id": c.get("q_id"),
            "preview": c["text"][:200] + ("…" if len(c["text"])>200 else "")
        } for c in chunks],
    }


def main():
    import shutil
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="Processed folder")
    args = ap.parse_args()

    root = pathlib.Path(args.dir).expanduser().resolve()

    manifests = []
    for md in sorted(root.glob("*.md")):
        if md.name.startswith("_"): continue
        file_id = slugify(md.stem)
        lines = md.read_text().splitlines()
        chunks = parse_file(lines)
        new_lines = inject_markers(lines, chunks, file_id)
        md.write_text("\n".join(new_lines) + "\n")
        m = build_manifest(chunks, file_id, md.name)
        manifests.append(m)
        print(f"{md.name}: {m['chunk_count']} chunks, {m['total_tokens']} tokens")

    agg_by_type = dict(sum(
        (collections.Counter(m["by_type"]) for m in manifests),
        collections.Counter()))
    total_chunks = sum(m["chunk_count"] for m in manifests)
    total_tokens = sum(m["total_tokens"] for m in manifests)

    # Append chunk stats + consolidated polish reports into a single _summary.md.
    summary = root / "_summary.md"
    lines_out = [summary.read_text()] if summary.exists() else []
    lines_out.extend([
        "", "## Chunking", "",
        "Atomic-block HTML chunk markers were injected inline in every `.md`. Downstream chunkers can split on `<!-- chunk:start … -->` / `<!-- chunk:end … -->` pairs and filter by `type` attribute.",
        "",
        f"- Total chunks: **{total_chunks}**",
        f"- Total estimated tokens: **{total_tokens:,}**",
        "- Chunk types:",
    ])
    for t, c in sorted(agg_by_type.items(), key=lambda x: -x[1]):
        lines_out.append(f"  - `{t}`: {c}")
    lines_out.extend([
        "",
        "### Per-file chunk counts",
        "",
        "| File | Chunks | Tokens |",
        "|------|--------|--------|",
    ])
    for m in manifests:
        lines_out.append(f"| {m['file']} | {m['chunk_count']} | {m['total_tokens']} |")

    # Fold in the verify report (if verify.py ran) — do this BEFORE polish
    # reports so readers see risk analysis near the top.
    verify_file = root / "_verify.md"
    if verify_file.exists():
        lines_out.extend(["", verify_file.read_text().rstrip(), ""])

    # Consolidate polish reports (if the polish stage produced any) into the
    # same _summary.md, then delete the reports folder.
    reports_dir = root / "_polish_reports"
    if reports_dir.is_dir():
        report_files = sorted(reports_dir.glob("*.md"))
        if report_files:
            lines_out.extend(["", "## Polish reports", "",
                              "One section per file — describes what each LLM polish agent kept / restructured / dropped.", ""])
            for rf in report_files:
                lines_out.append(f"### {rf.name}")
                lines_out.append("")
                lines_out.append(rf.read_text().rstrip())
                lines_out.append("")
        shutil.rmtree(reports_dir)

    # Clean up other intermediate artifacts we no longer keep on disk.
    for extra in ("_chunk_index.json", "_summary.json", "_verify.md",
                  ".pipeline-meta", "_chunks", ".snapshot"):
        p = root / extra
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()

    summary.write_text("\n".join(lines_out) + "\n")
    print(f"\nAggregate: {total_chunks} chunks, {total_tokens:,} tokens across {len(manifests)} files")


if __name__ == "__main__":
    main()
