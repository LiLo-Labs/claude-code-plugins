# How the plugin talks to the user

The user asked for a confirmation step before any color is chosen: identify the
parts, list them, iterate until the list is right, and only then propose colors.
That ordering matters. Color choices argued about in the abstract are wasted if
the part list underneath them is wrong, and a wrong part list is the failure mode
that cost the user six hours of prompting on this model.

So the loop is on identification, not on color.

## Stage 1 — detect (deterministic, no model reasoning)

`segment.py` runs these signals and merges them:

1. **Connected components.** Free and exact. On a flexi model each component is a
   link. 29 of them on the dragon.
2. **Dihedral creases.** Finds anything meeting the surface at an angle: eyes in
   sockets, plates, scutes, a nose horn sitting proud of the snout.
3. **Local thickness** (`paintlib/protrusion.py`). Finds smooth protrusions that
   leave no crease: horns, spikes, claws, teeth, fins. Ray-casting inward from
   each face gives the thickness of the solid; horns are thin and skulls are
   thick, and the boundary between them is the neck of the protrusion.

   **Not yet wired into `segment.py`.** The module is written and measured
   against the dragon (`docs/segmentation-findings.md`), but `segment.py` still
   runs only components and creases, so on that model both head horns remain
   inside one 27,468-triangle skull region. Until it is connected, stage 3 below
   is doing more work than it should have to.

Mirror symmetry pairs the results. Paired features are the strongest anatomical
signal available and pairing doubles as a check on the segmentation itself.

## Stage 2 — propose (model reasoning)

Claude reads the segment table plus the segmentation render and proposes a named
part list:

```
  head
    L eye / R eye          paired, 689 / 682 triangles
    head horn L / R        paired, 1593 / 1734, protruding, top
    nose horn              on midplane, front
    brow ridge L / R       paired, small
  body
    links 1-14             one per component
    belly plates           paired, underside
```

Every proposed part carries the evidence behind it (paired, protruding, thin,
area, where it sits) so the user can judge the claim, and a confidence marker.
Unassigned regions are listed explicitly as "not identified" rather than quietly
folded into the body -- an unlisted region is the one the user will notice missing.

## Stage 3 — iterate (the human-in-the-loop)

The user corrects the list in plain language, by name, never by coordinate:

| the user says | the plugin does |
|---|---|
| "those aren't ears, they're fins" | rename the part |
| "you missed the spikes down the tail" | re-run detection on named components with a lower threshold, propose what it finds |
| "the two lumps by the nose are nostrils" | rename, and pair them if they mirror |
| "merge the jaw into the head" | merge parts |
| "split the tail into tip and base" | sub-segment that part only |
| "show me part 7" | render that part highlighted |

Each edit is answered with an updated render, because a part list read as text is
not the same as a part list seen on the model. The loop ends when the user says
the list is right. The confirmed list is saved next to the model so a later run
skips straight past detection.

## Stage 4 — color options

Only now does color enter. Claude proposes two or three distinct plans against the
loaded filaments -- not one take-it-or-leave-it answer -- each with a render and a
one-line reason per assignment. Rules that always hold: symmetric partners get the
same color; the largest-area part takes the base color; the highest-contrast
filament is reserved for the smallest high-salience parts (eyes, teeth, claws).

## Stage 5 — apply

`apply_plan.py` writes the 3MF, then proves it did no harm: `geometry_matches()`
compares triangles, vertices and placement against the input and refuses to emit a
file that differs. Adjustments after this point ("make the spikes filament 3") edit
the plan and re-run from stage 4 only. Detection never re-runs, because it is
deterministic and the answer would be identical.
