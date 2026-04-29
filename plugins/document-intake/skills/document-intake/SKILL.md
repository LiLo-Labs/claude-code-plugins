---
name: document-intake
description: Use when the user has a folder of mixed-format documents (PDF, DOCX, XLSX, CSV, PPTX, EML, VSDX, etc.) and wants them converted into clean, LLM-ready markdown with embedded image descriptions, semantic cleanup, verification, and inline chunk boundaries for downstream RAG/search/review.
---

# Document Intake Pipeline

Converts a folder of heterogeneous documents into polished, chunked markdown suitable for human review and LLM ingestion. Handles the four common problems with naive PDF → text conversion:

1. **Binary formats lose structure** — headings, tables, columns, and labels get flattened to an unstructured text stream.
2. **Embedded images have no descriptions** — decorative bullets pollute the output while meaningful diagrams are lost.
3. **Page-level noise repeats** — running headers, copyright lines, timestamps, and page counters appear on every page.
4. **Downstream chunking is arbitrary** — RAG pipelines split on fixed character counts, breaking Q/A pairs and tables.

## Output layout (raw → final, single flat folder)

Given an input folder `INPUT/`:

```
INPUT/
  foo.pdf
  bar.docx
  …
  processed/                         ← single output folder
    foo.md                           ← final polished, chunk-marked
    bar.md
    …
    embedded_images/                 ← extracted images
    _summary.md                      ← cleanup audit + chunk stats + verify report + polish reports
```

Just `.md` files, `embedded_images/`, and `_summary.md`. Chunk boundaries are inline as `<!-- chunk:start … -->` / `<!-- chunk:end … -->` HTML comments so any markdown-aware chunker (LangChain, LlamaIndex, custom splitter) can read them.

## Pipeline stages

| Stage | Script | What it does |
|-------|--------|--------------|
| 1. Convert | `scripts/convert.py --input <source>` | PDF/DOCX/XLSX/CSV/PPTX/EML/VSDX → markdown in `processed/`. Extracts embedded images to `processed/embedded_images/<safe-name>/` and writes `**Embedded image (page N, image M):** \`embedded_images/<safe>/pageN_imgM.png\`` placeholders inline. Image-extraction fallback: if pymupdf colorspace conversion fails, raw embedded bytes are saved with the native extension — no image is silently dropped. |
| 2. Embed images | `scripts/embed_images.py --dir <source>/processed` | Replaces image placeholders with descriptions. Tiny images (<15 KB) → terse `*[decorative icon]*` tags. 15–50 KB → `*[small graphic]*`. ≥50 KB → fallback size-tier tag. Accepts `--author-descriptions <json>` to inject hand-written descriptions for specific images (recommended for any image you want preserved verbatim). |
| 3. Deterministic cleanup | `scripts/cleanup.py --dir <source>/processed` | Generic, document-agnostic rules (no hardcoded vendor strings): strip page headers/footers/copyright, auto-detect repeating running headers, join PDF column-wrap line breaks, structure OneTrust-style Q/A (`N.M` → `**Q**/**A:**`), restructure risk records, emit per-file audit trail to `_summary.md`. Also writes a snapshot to `processed/.snapshot/` so stage 6 (verify) can diff. Operates IN PLACE. |
| 4. LLM polish | `prompts/polish_document.md` template | Dispatch one sub-agent per polished file with the polish prompt. Adds semantic `##` headings, reconstructs tables, resolves orphan content leaks, **flags sentence fragments** (rules 10 & 11), writes a per-file kept/restructured/dropped report to `processed/_polish_reports/`. Operates IN PLACE. |
| 5. Verify | `scripts/verify.py --dir <source>/processed` | Diffs `.snapshot/` vs polished output. Deterministic checks: identifier preservation (RITM/REQ/DMND/SFSTRY/PRJ/TASK/email/URL/dollar/date/port), number preservation, named-entity preservation, word-count ratio, 5-gram Jaccard similarity, and **sentence-fragment detection** (quantifier-no-number, dangling-preposition, currency-no-amount, numeric-question-echo-answer). Writes `_verify.md`; flagged files get CRITICAL / WARN labels. |
| 6. Chunk boundaries | `scripts/chunk.py --dir <source>/processed` | Walks each polished `.md`, identifies atomic semantic blocks (Q/A, RISK, image description, table, metadata, heading+prose), injects inline HTML comment markers `<!-- chunk:start/end -->`. Folds `_verify.md` and every per-file polish report into the final `_summary.md`, then deletes `_polish_reports/`, `.snapshot/`, and any other intermediate artifacts so only `.md` files + `embedded_images/` + `_summary.md` remain. Operates IN PLACE on the `.md`. |

## How to run from the slash command

The plugin exposes `/intake <path-to-folder>` (see `commands/intake.md`). It runs all 6 stages, dispatches polish agents in parallel, and consolidates everything into `<path>/processed/_summary.md`.

## When to invoke

- User has a folder of intake / onboarding / due-diligence documents.
- User says "make these LLM-readable" / "feed these into RAG" / "chunk these for search".
- User asks to convert Office / PDF / CSV / email files to markdown.
- User complains that PDF-extracted text is messy, has line-wrap breaks, or is full of irrelevant page noise.

## Not a good fit for

- Single-document quick extraction (just call `pymupdf` directly).
- Highly structured data already shaped (use pandas).
- OCR of scanned PDFs (this skill assumes text-layer PDFs; add a Tesseract step upstream if needed).

## Reusability notes

- The deterministic stages have **no document-specific hardcoded strings**. Heuristics (TitleCase label detection, page-section running-header repetition counts, Q&A numeric patterns) generalise.
- The polish prompt template takes a `{DOC_TYPE_HINT}` so the sub-agent knows what structure to impose.
- All scripts accept `--input` / `--dir` arguments. Nothing is hardcoded to a specific project path.
- Pipeline is idempotent on its output: re-running stages 2–6 again on the same `processed/` folder re-applies cleanup/polish/verify/chunking. Stage 1 is destructive (re-creates the folder from source).
