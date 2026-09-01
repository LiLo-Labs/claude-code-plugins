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

## The 20-part run, and what it settles

    102 calls, $45.95, 3.9 hours, 3MF geometry IDENTICAL
    rocky base 24.9% | shell body 29.3% | silt 19.1% | crack lines 8.0%
    the other sixteen parts between 0.0% and 3.4%

Asked with no colour limit, SEE names 36 parts on this model and finds real
levels: ribs -> rib crests -> rib troughs; barnacle clusters -> individual
cones -> mouth openings; kelp stipes -> tips -> holdfasts; plus growth lines,
nacre patches, a mineral waterline and algae film. The identification has
never been the weak part.

Half the views of the continuous render look like a painted model: the shell
one ochre material across body, coils and ribs, dark wet rock below, pale silt
in the low pockets, the junction on the real boundary.

## What is still wrong: a thin feature in a CRAZED FIELD

Crack lines took 8.0% of the surface and flood the plated area of the upper
coil in half the views. The fine brush stops a line from filling a loop, but
a crazed field is dozens of fissures criss-crossing a plated surface, and
seventy one-pixel strokes across it sweep up most of the plates between them.
Silt is the same shape of error at 19.1%.

This is the open problem. It is NOT the rib/body boundary, which the filament
stage dissolves, and it is not resolution -- the panels are large and the
camera goes in close now.

## Judge the FILAMENT render, not the part render

The part render shows ten colours and its upper coil looks patchy, because
ribs and shell body are the same material and their boundary is a judgement --
they trade surface between rounds. That flaw does not reach the print. Asked
which filament each part wants, the agent puts ribs and body BOTH in bone, so
the boundary it was arguing about vanishes. As laid down:

    slate 57.1% (the rock)   bone 31.3% (the shell)
    rust   8.9% (spiral eye and breaks)   moss 2.8% (weed)

and the rock/shell split is clean in every view. Some rust speckles the coil
in views 2 and 5, where the cracks took shell surface; that is the real
remaining defect and it is much smaller than the part render suggests.

Render `field.npy` mapped through `filaments.json` before concluding anything
is wrong with a run.

## Do not rebuild these

Four rules for deciding a boundary without looking were built and measured on
identical inputs: climbing the merge tree, shortest path over the border
graph, matching the surface signature, and letting a part reach as far as its
own marks are apart. All four drew distance bands or confetti. The measurement
that ends the argument: above a seed on the ribs the ancestor chain runs
0.132% then 33.989% of the surface -- the ribs are not a node, so no way of
choosing among nodes can produce them.
