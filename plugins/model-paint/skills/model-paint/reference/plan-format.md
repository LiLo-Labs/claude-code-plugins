# plan.json

The contract between judgment and plumbing. `apply_plan.py` refuses anything it
cannot resolve exactly rather than skipping it, because a silently skipped
assignment shows up as bare plastic six hours into a print.

```json
{
  "filaments": [
    {"index": 1, "name": "Slate Grey PLA", "hex": "#4a5058"},
    {"index": 2, "name": "Bone White PLA", "hex": "#e8e0cf"},
    {"index": 3, "name": "Black PLA", "hex": "#1a1a1a"}
  ],
  "assignments": [
    {"segment_id": "s02", "filament": 3, "reason": "left eye, darkest filament on the smallest feature"},
    {"segment_id": "s03", "filament": 3, "reason": "right eye, matches its pair"},
    {"segment_id": "s04", "filament": 2, "reason": "left horn, bone reads clearly against the slate body"},
    {"segment_id": "s05", "filament": 2, "reason": "right horn, matches its pair"}
  ],
  "default_filament": 1
}
```

## Fields

| Field | Rule |
|---|---|
| `filaments[].index` | 1..16, unique, in the user's loaded nozzle order. Index n prints from extruder n and takes `filament_colour[n-1]` in the project config. |
| `filaments[].name` | The user's own name for the spool. Appears in the summary table they read. |
| `filaments[].hex` | `#rrggbb`. The real color - it drives both the preview render and what OrcaSlicer shows on open. |
| `assignments[].segment_id` | Exactly an `id` from the segments.json the plan was written against. |
| `assignments[].filament` | One of the listed `index` values. |
| `assignments[].reason` | Required. One clause, user-facing: feature name plus intent. No ids, no coordinates, no field names. |
| `default_filament` | One of the listed indices. Unassigned triangles are left unpainted and fall back to this as the object's extruder. |

Do not add fields. `preview.py` will honor a raw `faces` list on an assignment,
but `apply_plan.py` will not - it resolves every assignment through
`segment_id`, so a plan built on `faces` renders and then fails at apply time.
Always name a segment: it is what keeps the plan reviewable and keeps face
indices out of the reasoning.

## Checklist before writing the file

- Every `symmetry_partner` pair carries the same filament.
- Every `filament` value appears in `filaments`; `default_filament` does too.
- Every `segment_id` exists in segments.json, spelled identically.
- The largest-area region has no assignment - it is the default.
- No two assignments name the same segment.
- No assignment lands on a degenerate planar patch or an interior joint surface.
- Every reason names a feature a human can point at.

## Errors and what they mean

| Message | Cause | Fix |
|---|---|---|
| `the plan assigns N segment(s) that the segments file does not contain` | id typo, or the plan was written against a different segmentation run | Re-read `summary.segments`; ids are only stable within one run |
| `assignment for 'sNN' uses filament N, which the plan does not list` | assigned an index with no `filaments` entry | Add the filament or change the index |
| `default_filament N is not one of the listed filaments` | default points at an unloaded slot | Set it to the base color's index |
| `makes no assignments; nothing to paint` | every region fell through to the default | The plan says nothing; name at least one feature |
| `segment 'sNN' names object 'X', which is not in the model` | segments.json and the model do not match | Re-run `segment.py` on the exact file being painted |
| `geometry changed` from the verify step | should never happen; the output is deleted automatically | Report it, do not retry with different flags |

Overlapping assignments do not fail - the last one wins and the conflict count is
reported. If the summary shows conflicts you did not intend, two segments cover
the same triangles and one of them is the wrong region.

## Determinism

Same model and same decisions produce the same file. Sort `filaments` by index
and `assignments` by segment id, and do not put timestamps, paths, or run notes
in the plan.
