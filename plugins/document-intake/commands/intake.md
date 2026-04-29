---
description: Convert a folder of mixed-format documents into polished, chunked markdown ready for RAG / search / review
---

## Your task

The user wants to run the document-intake pipeline on a folder. The arguments they passed are: `$ARGUMENTS`

If `$ARGUMENTS` is empty, ask the user for the absolute path to the source folder and stop.

If `$ARGUMENTS` is a path, treat it as `<INPUT>` and run the pipeline below. Output goes to `<INPUT>/processed/`.

## Step 1 — Validate the input folder

Run: `/bin/ls -la "<INPUT>"` and check that it exists and contains source documents (PDF, DOCX, XLSX, CSV, EML, VSDX). If the folder is missing or empty, report and stop.

## Step 2 — Stages 1, 2, 3 (deterministic, scripted)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/convert.py"      --input "<INPUT>"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/embed_images.py" --dir "<INPUT>/processed"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cleanup.py"      --dir "<INPUT>/processed"
```

If any stage prints errors, stop and surface the error to the user.

## Step 3 — Stage 4 (LLM polish — agent-driven)

After cleanup completes, list every `.md` file in `<INPUT>/processed/` (excluding `_`-prefixed metadata files). For each file, dispatch a sub-agent in parallel (batch size 6 is comfortable; larger batches risk rate limits) with the polish prompt template.

The polish prompt is at `${CLAUDE_PLUGIN_ROOT}/prompts/polish_document.md`. For each agent, substitute:
- `{FILE_PATH}` → absolute path to the polished `.md`
- `{REPORT_PATH}` → `<INPUT>/processed/_polish_reports/<same-filename>.md`
- `{DOC_TYPE_HINT}` → infer from filename and content (e.g. "OneTrust questionnaire export", "PitchBook profile", "ServiceNow ticket", "project charter", "policy document", "email", "meeting minutes", "tax form", "Visio diagram", "CSV report")

Agents write their polished output back to the same file in place and write a Kept/Restructured/Dropped/Notes-for-reviewer summary to the REPORT path. Wait for all agents to complete before proceeding.

## Step 4 — Stage 5 (verify — deterministic)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify.py" --dir "<INPUT>/processed"
```

The verifier reads `<INPUT>/processed/.snapshot/<file>.md` (pre-polish) and diffs against the post-polish `<file>.md`. It flags files where polish may have dropped substantive content. Report the verifier's counts to the user (e.g. "X CRITICAL, Y WARN, Z clean"). If any file is flagged CRITICAL, prompt the user whether to dispatch spot-check agents or proceed.

## Step 5 — Stage 6 (chunk + consolidate)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/chunk.py" --dir "<INPUT>/processed"
```

This injects inline `<!-- chunk:start/end -->` markers, folds the verify report and every per-file polish report into `_summary.md`, and deletes the now-redundant `_polish_reports/`, `.snapshot/`, and other intermediate artifacts.

## Step 6 — Final report

Tell the user:
- How many source files were processed
- The output location: `<INPUT>/processed/`
- The total chunk count and estimated token count from the chunk stage
- Any files that the verifier flagged as CRITICAL or WARN, with a one-line reason each
- Where to read the consolidated audit: `<INPUT>/processed/_summary.md`

Keep the final report concise — under 200 words.

## Notes

- `${CLAUDE_PLUGIN_ROOT}` is automatically set by Claude Code to this plugin's root directory.
- The pipeline is idempotent on stages 2–6 — running again won't break the polished output, but it will re-inject chunk markers (cleanly stripping the old ones first if the user asks for a re-run).
- For sensitive images (a vendor decision matrix, a critical diagram), the user can pre-author descriptions in a JSON file and pass `--author-descriptions <file>` to stage 2. Template at `${CLAUDE_PLUGIN_ROOT}/prompts/example_image_descriptions.json`.
