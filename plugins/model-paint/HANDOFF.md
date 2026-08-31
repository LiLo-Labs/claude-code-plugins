# Handoff

## What this is now

One command, `python3 -m paintpipe.cli`, that paints a model by looking at it.
Twelve modules; see `paintpipe/README.md` for what each does and
`docs/failure-circumstances.md` for what was tried and what it cost.

    LOOK    rig.plan_poses picks where to stand by what the views can see
    SEE     what parts the piece has, how detailed each is, what order to paint
    PAINT   one colour at a time, marked in every view that shows it, a little
            each round, LOOKING AFTER EVERY STROKE until that colour is right
    REVIEW  the whole painting at once -- the only pass allowed to say that a
            later coat ruined an earlier one
    CHOOSE  which of the loaded filaments each part prints in
    EXPORT  the 3MF, with the geometry proved identical to the input

## Last measured run (scallop-shell-barricade.stl, 11 parts)

    36 calls, $16.57, 86 minutes, 3MF geometry IDENTICAL
    rocky base 52.3% | shell body 26.6% | spiral centre 5.1% | ribs 3.7%
    cracked shell 2.6% | cracks 2.6% | weed 2.8% | rim 2.2%
    barnacles 1.0% | limpets 1.1%

Two large areas and a set of genuinely small details, which is what the object
is. For comparison, the run before the review pass existed gave "rubble" 13.2%
and "spikes" 18.4% -- details eating the model. The review moved 5074, then
1330, then 4039 regions across three rounds.

Filament choice is asked, not solved. It answered: cracks -> slate, "dark
recessed lines; slate acts as the shadow"; ribs -> bone, same as the body,
"the deep ribbing already reads". That is a painter using four colours, and no
Lab-distance solver produces it.

## What is still wrong

The upper coil is patchy in the views that see it obliquely (2 and 5 of six).
Ribs and body are the same material and the boundary between them is a
judgement, so they trade surface across rounds. Views 0, 3 and 4 are clean.

## Do not rebuild these

Four rules for deciding a boundary without looking were built and measured on
identical inputs: climbing the merge tree, shortest path over the border
graph, matching the surface signature, and letting a part reach as far as its
own marks are apart. All four drew distance bands or confetti. The measurement
that ends the argument: above a seed on the ribs the ancestor chain runs
0.132% then 33.989% of the surface -- the ribs are not a node, so no way of
choosing among nodes can produce them.
