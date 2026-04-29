# Document Intake Plugin

Converts a folder of mixed-format documents (PDF, DOCX, XLSX, CSV, EML, VSDX) into clean, polished, chunkable markdown — ready for RAG ingestion, semantic search, or human review.

## What it does

```
INPUT/                                              INPUT/
  vendor_review.pdf                                   processed/
  pitchbook_profile.pdf                                 vendor_review.md          ← polished + chunk-marked
  signed_contract.docx          /intake INPUT          pitchbook_profile.md
  expense_report.xlsx          ─────────────────►      signed_contract.md
  meeting_notes.eml                                     expense_report.md
  architecture.vsdx                                     meeting_notes.md
                                                        architecture.md
                                                        embedded_images/        ← extracted, described
                                                        _summary.md             ← audit + verify + polish reports
```

Every source document gets a 1:1 `.md` sibling. All metadata (cleanup audit, verification report, per-file LLM polish reports) is consolidated into a single `_summary.md` so you don't drown in subdirectories.

## Why this over a one-shot pymupdf conversion

| Naive `pymupdf → text` | Document Intake plugin |
|---|---|
| PDF column wrap creates mid-sentence line breaks | Joined back into paragraphs |
| Page headers / copyright lines on every page | Auto-detected & stripped |
| Embedded decorative icons clutter output | Tagged & dropped (size-tiered) |
| Embedded diagrams produce no description | Authored descriptions optional, fallback tags otherwise |
| Q/A questionnaires (OneTrust, ServiceNow, PitchBook) flatten to noise | Recognised; questions paired with answers as `**Q N.M** — … **A:** …` |
| RAG splits on character count, breaks Q/A pairs and tables | Inline `<!-- chunk:start/end -->` markers around atomic blocks |
| No way to tell whether content was lost | Deterministic verify stage with snapshot diff + sentence-fragment detection |

## Commands

| Command | Description |
|---------|-------------|
| `/intake <path>` | Run the full 6-stage pipeline on the folder at `<path>`. |
| `/intake` | Prompt for a path. |

## Pipeline stages

1. **Convert** (`convert.py`) — PDF/DOCX/XLSX/CSV/EML/VSDX → markdown + extracted images. Image extraction has a graceful fallback: exotic colorspaces fall back to raw bytes with native extension; truly broken images get an explicit `*[image extraction failed: …]*` placeholder so nothing silently disappears.
2. **Embed images** (`embed_images.py`) — placeholder → description. Optional `--author-descriptions <json>` for hand-written descriptions of important images.
3. **Cleanup** (`cleanup.py`) — generic, document-agnostic noise removal (no hardcoded vendor strings). Drops decorative-image placeholders, running page headers/footers, page counters, copyright. Heuristically structures Q/A and risk records. Saves a `.snapshot/` for the verify stage.
4. **Polish** (LLM, agent-driven) — one sub-agent per file. Adds semantic `##` headings, reconstructs tables, resolves orphan content leaks, **flags & repairs sentence fragments** (quantifier-no-number, dangling preposition, echoed-context answer to a value-type question).
5. **Verify** (`verify.py`) — diffs pre-polish snapshot vs final polished. Identifier preservation, number preservation, named-entity preservation, word-count ratio, 5-gram Jaccard similarity, and sentence-fragment regex sweep. CRITICAL / WARN flags surface anything suspicious for human spot-check.
6. **Chunk** (`chunk.py`) — atomic-block boundary detection (Q/A pair, RISK record, image description, markdown table, heading+prose, metadata bullet list). Injects HTML comment markers inline. Folds all metadata into `_summary.md` and deletes intermediate folders.

## Output anatomy

```
processed/
  *.md                          ← polished markdown, chunk markers inline
  embedded_images/<stem>/*.png  ← extracted images, referenced by the .md
  _summary.md                   ← single audit file:
                                    - Cleanup section (per-file drop counts)
                                    - Chunking section (per-file chunk counts, type breakdown)
                                    - Verification section (thresholds, flagged files, fragments)
                                    - Polish reports section (per-file Kept/Restructured/Dropped/Notes)
```

## Inline chunk markers

Every atomic block in the polished `.md` is wrapped:

```md
<!-- chunk:start id="vendor-review::qa::2.5" type="qa" tokens="220" parent="ois-determinations" -->
**Q 2.5** — Is an ISA required for this engagement?
**A:** Yes
<!-- chunk:end id="vendor-review::qa::2.5" -->
```

Chunk types: `qa`, `risk`, `image`, `table`, `metadata`, `heading`, `bullet_list`, `prose`. Any markdown-aware chunker can split on the comments; LangChain `MarkdownHeaderTextSplitter` and LlamaIndex `MarkdownNodeParser` work without configuration.

## Dependencies

- Python 3 with `pymupdf` (PDF), `python-docx` (DOCX), `openpyxl` (XLSX), `Pillow` (image manipulation). All four are widely available; install via `pip install pymupdf python-docx openpyxl Pillow`.
- Standard-library modules only for CSV (`csv`), EML (`email`), VSDX (`zipfile` + regex on shape XML).

## License

MIT.
