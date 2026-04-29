# Polish prompt template (stage 4)

Dispatch one sub-agent per file with the following prompt. Substitute the `{FILE_PATH}`, `{REPORT_PATH}`, and `{DOC_TYPE_HINT}` placeholders before sending.

---

You are polishing a single pre-cleaned markdown file for human + LLM review. The file was machine-extracted from a source document (PDF / DOCX / XLSX / EML / VSDX) and then passed through a deterministic cleanup script. Your job is to apply semantic judgment the regex couldn't.

FILE TO POLISH (read it, rewrite it in place):
`{FILE_PATH}`

Document-type hint (may be empty; rely on content if so): **{DOC_TYPE_HINT}**

## Apply these changes

1. **Top metadata block** — if the file starts with a dense run of `Field Value Field Value …` metadata, convert to a clean `## Metadata` section with bulleted `- **Field:** Value` lines. Drop fields whose value is empty, zero-count, or just the field name echoed back.

2. **Section headings** — insert `##` section headings wherever the document has a natural topic change. For questionnaires, group Q/A by section number. For reports, group by subject. Name each section from inline cues in the source text (don't invent names).

3. **Q/A pairs** — keep the `**Q N** — question / **A:** answer` format where present. If an Answer is `(not answered)` AND the question text is purely an instruction/preamble (no real response expected), drop the `**A:** (not answered)` line.

4. **Explanation leaks** — any line like `**Explanation:** None <trailing text>` means the explanation was empty but a downstream section heading or paragraph leaked in. Move the trailing text to its own `##` section if it's substantive, or drop the line entirely if it's just a section label.

5. **Risk records** — if any `**RISK**` records appear fragmented across bullets, recombine into one clean record:
   - **Description:**, **Category:** / **Stage:** / **Approver/Owners/Deadline:**, **Treatment plan:**, **Result:** / **Closed:**.

6. **Tables** — where the source clearly came from a table but the extraction produced a stream of field-label bullets with consistent columns, reconstruct as a proper markdown table. Don't invent columns — only reconstruct when the structure is unambiguous.

7. **Duplicated content** — if the same paragraph repeats because a PDF footer got pulled into body text on multiple pages, keep ONE canonical copy and delete the duplicates.

8. **Image descriptions** — preserve all `**[Image — …]**` lines that have substantive content. Drop any leftover `*[decorative icon]*` / `*[small graphic]*` markers.

9. **Don't shorten or remove substantive content** — you're restructuring, not summarizing. Every fact present in the input must still be present in the output.

10. **Flag and repair sentence fragments / missing values.** Before you finish, scan every `**A:**`, `**Explanation:**`, and bullet value for these red flags. Each red flag means the extractor probably dropped the rest of the content; recover it from the raw extracted text (or the source document if needed) and put it back.

    Red flags to look for — the answer:
    - Ends with a quantifier word but no number: `Less than`, `Greater than`, `More than`, `Fewer than`, `At least`, `Up to`, `Over`, `Under`, `At most`, `Approximately`, `Between X and`, `From X to`.
    - Ends with a preposition, article, or conjunction: `of`, `to`, `for`, `with`, `by`, `from`, `the`, `a`, `an`, `and`, `or`, `but`.
    - Is a currency or unit prefix with no number: `$`, `USD`, `port`, `page`, `section`, `item`, `chapter`.
    - Is a single short token that doesn't answer a value-type question: e.g., Q asks "Tax ID number" → A is just the vendor name or `Unknown`. That means the real TIN was likely dropped.
    - Ends mid-phrase with no terminating punctuation AND the question clearly expects a value (`how many`, `what is the number`, `what date`, `what percentage`, `provide your X`, `enter X`).
    - Is the echoed question context (e.g., `Vendor Name | Org | Unknown`) for a question that asks for something other than a name.

    For each red flag: look in the raw extracted text (or the source file) for the actual answer — it's often on the next bare line after the echoed context. If you cannot find it, leave the answer as `(value missing in source extraction — see original document)` and note the file + Q-number in your report's **Notes for reviewer** section.

11. **Also flag truncated prose.** Any heading or paragraph that ends mid-sentence without terminal punctuation, or starts mid-phrase (lowercase first word, no subject), is a likely extraction break. Join with the previous or next line if the continuation is obvious. If it isn't, flag it in **Notes for reviewer**.

## After polishing

Write a SEPARATE summary file at:
`{REPORT_PATH}`

Summary format (<200 words, markdown) with exactly these sections:

- **Kept:** — the substantive content that remains.
- **Restructured:** — what you reformatted and why.
- **Dropped:** — any content you removed, with reason.
- **Notes for reviewer:** — anything ambiguous, unusual, or requiring human judgment.

## Response back

Reply with ONE sentence confirming completion. Do not output the polished content or the summary — just a short confirmation so the orchestrator knows you finished.
