# The circumstances under which this pipeline fails

Every failure in the validation sweep reduced to one of eleven structural
circumstances. None of them is a model being bad at looking; each is a
mismatch between where the evidence lives and where the decision is made.
Each carries the invariant that now guards it, and the incident that paid
for it. When a new failure appears, place it here first: a failure that
does not fit a listed circumstance is a new circumstance, and that is the
real finding.

## 1. Volumetric identity, superficial evidence

Every labelling unit -- atom, vote, audit correction, boundary -- lives on
the surface graph. Object identity is volumetric. A fin's two sides are one
thing, yet geodesically they connect only around the rim, so every
per-surface stage can decide each side independently.

*Incident:* the fish wore its pectoral label as a stripe down the flank and
its tail-fin label on the dorsal blade's back face.
*Invariant:* thin sheets are welded into single units by inward ray pairing
(thin relative to local face scale) and take one label whole
(`consensus.unify_blades`).
*Watch for:* shells within shells, hollow casts, interleaved plates --
any "same thing" spanning disconnected surface territory.

## 2. A judgement inherits its render's losses

Every decision is mediated by a picture. Whenever the framing loses the
answer -- a camera rolled off the object's up, a claim occluded in the
chosen view, an iris too small in a context frame -- the judgement is
confidently wrong about something it was never shown.

*Incidents:* naming and audit cameras rolled with azimuth on every model
whose up was not file Z; both real tusks "refused" from a view with zero
claim pixels; the iris folded into the lid from a frame where it was a dot.
*Invariant:* no verdict stands whose input could not have contained the
answer. Cameras take the chosen up; confirm gates try several directions
and report UNSEEN rather than no; identity asks carry both close and
context scales and move faces only on two-angle agreement.

A quieter form of the same loss, and the one that caps RECALL rather than
correctness: an orbit is a set of compromises. Every orbit camera sits on
the bounding sphere and frames the whole model, so an instance on a steeply
turned facet is foreshortened in all of them at once and no amount of
orbiting fixes it -- the orbit never leaves the sphere. And every look asks
the same open question, so attention lands on the same conspicuous instances
each time.

*Incident:* the shell's barnacle survey, where 162 looks over 18 orbit
cameras indexed the same conspicuous cones repeatedly and left a scatter of
small or edge-on ones untouched.
*Invariant:* the survey looks twice, and the second pass LEAVES THE SPHERE --
each of its cameras sits on the outward normal of an unindexed look-alike and
looks straight in, so an edge-on instance finally gets a face-on look. Aiming
by geometric signature is not labelling: what is at the end of the aim still
has to be pointed at and still has to pass consensus (`index3d.survey`).
*Measured:* 77 instances from the orbit alone; 102 once the vote bar stopped
punishing instances the cameras only reached once; 120 with 96 aimed looks.

The half of that fix which did NOT work is the more useful finding. The
second pass also tints what the first pass found and asks "what did we
miss", and re-asking the ORBIT looks under that question returned three
instances for 162 vision calls, against three for 24 aimed looks -- seven
times the yield per look, at a seventh of the cost. Attention was never the
binding constraint. A better question cannot recover an answer the viewpoint
does not contain; only a different viewpoint can. The tint stays, because it
is free and it sharpens the aimed looks; the re-ask was cut.

The consequence for the gate: a bar of two votes is unreachable for an
instance the cameras only ever reached once, which rejects it for the
cameras' failing rather than its own. The bar is the smaller of the asked-for
count and the number of looks that actually contained the node -- seen twice,
agreed twice; seen once, agreed once -- with the share gate keeping it honest,
since a node offered to ten views and pointed at in one still fails.

## 3. Priors beat weak evidence

Any text an agent reads -- user intent, prompt examples -- acts as a prior
strong enough to beat faint pixels. Assert tusks and the pipeline will hunt
tusks; write "2 for paired eyes" as an example and a cyclops trends toward
two.

*Incidents:* the ogre's invented tusks (asserted in a test intent); the
count field's own examples.
*Invariant:* observation outranks assertion. Counts are what the studying
agent counted in the renders, null when uncountable; "my count was wrong,
there are no more" is documented as a correct answer; the /paint command
warns the user against asserting features their model does not have.

## 4. Look-alikes at the wrong scale

The detail that separates an eye from an ear-cup, a face from a fold
cluster, lives below the resolution of the view making the call.

*Incidents:* the ogre's chin folds took the eye and nose labels while the
real face was named "bald cranium"; forehead slit pits read as a matched
eye pair; the cow's ear cups read as eyes from the front.
*Invariant:* identity is established at study scale (the dossier, upright
eye-level views, explicit cautions naming this model's traps), verified at
close scale (per-instance looks), and a label moves only when the scales
agree.

## 5. Cache identity is not question identity

A cached answer is only as reusable as its key is honest. A key that does
not digest the full question -- the images shown, the vocabulary offered,
the orientation, the reply contract -- replays an answer to a different
question, silently.

*Incidents:* constant keys replayed the first painter scheme, the first
critique, and the first vocabulary a directory ever produced; naming keys
without the vocabulary replayed old votes against renamed parts and cost
the cow its horns.
*Invariant:* every ask key digests its stimuli and contract. This class
produced the most misleading results of the sweep, because everything
looked like it ran.

## 6. Judgement without selection

A binary gate wired to a mechanical consequence destroys information even
when the judgement is right. "Not tusks" cannot say what the region is;
reassign-to-nearest-neighbour decides anatomy by adjacency arithmetic.

*Incidents:* the binary confirm stalemate (the gate was right every time
and nothing was ever kept); horns and ears swapped into each other by
refuse-then-dump; a third of the hide dropped into "ears".
*Invariant:* every gate exits through selection among explicit candidates
-- prune keeps a subset, design cuts are picked from numbered drawings,
a doubted instance is re-identified against the labels actually present,
and "none of these" changes nothing.

## 7. An optimizer spends the freedom it is given

Give a colour assigner four filaments and it finds four jobs; give a
painter unlimited colour and it spends it at part granularity. Aesthetic
judgement fills whatever space the constraints leave, so the constraints
must encode ontology, not taste.

*Incidents:* a bald crown painted white to break up a grey lump; black
spent on ear hollows; a 59%-area body as one flat swatch under an
unlimited palette.
*Invariant:* parts carry materials and non-accent parts of one material
paint alike, enforced after all argument ends; painter and critic are told
no filament needs a job; the unlimited stage shades within parts and
feathers across smooth boundaries, and a design critic must pass the
continuous result before the limiter runs.

## 8. A scattered family loses to its host

A part that is a FAMILY of many small pieces -- barnacle fields, rivet
rows, scale patches -- has no single blob to win. Per-atom majority voting
hands most members to the label they grow on, because each piece alone is
too small to carry its atom; the label survives as a token few instances
and the print shows the family in two colours.

*Incident:* the shell's barnacle fields: ~1% of the surface carried the
barnacle label while sister fields sat unlabelled inside "growth terraces",
so repainting the label recoloured only a handful of clusters.
*Invariant:* the confirmed members define a geometric signature
(characteristic radius and relief sign), look-alike patches on host labels
are sized against the family's own pieces, and each candidate passes the
two-angle selection gate before any face moves
(`refine.recover_scattered_families`).

A cousin incident with the same shape but the opposite direction: the
material-harmonization pass overruled the critic's barnacle promotion
because the vocabulary had tagged barnacles "shell" material. A material
tag is a prior written before anyone saw the finished piece; the critic's
override is an observation of it. Observation outranks assertion (see 3),
so critic-overridden parts are exempt from harmonization.

## 9. A repair proposes what it can draw, not what is there

Every recovery stage ends in a proposal: here is the region I think this part
occupies. When those proposals are SYNTHESISED -- rings grown from a pixel
stencil, discs of camera-facing surface, floods bounded by a crease angle --
they cannot follow a sculpted margin, so the confirm gates refuse them and
the feature stays unpainted forever. The judges were never the problem; the
proposers were.

*Incidents:* the dragon's eyes, refused as discs and bands and floods for a
whole session while they existed all along as merge-tree nodes 53 and 54; the
shell's barnacles and the reef's colonies, hunted with candidates sized from
the fragments the family already held, so every sheet came back a sliver on a
colony's edge and every reviewer correctly said no.
*Invariant:* proposals come from the geometry's own structures first. The
relocate ladder offers merge-tree nodes near the located anchor before any
drawing, and the scattered-family sweep sizes its hunt by the characteristic
radius the scale-space index measured for that family -- not by what the
label currently holds. Synthetic drawings remain, but only as the fallback
for a feature that exists in the design and not in the mesh.
*Watch for:* a stage that refuses nearly everything it is offered. A gate at
0/36 is evidence about the candidates, not about the model.

## 10. A label field edited finer than its evidence

Labels are decided per atom, per region, per confirmed instance -- but the
field they live in is per face, and every stage was free to write single
triangles into it. A boundary that is not a region edge is not a geometric
edge at all, so those writes accumulated as ragged colour seams that no
amount of downstream smoothing could make crisp.

*Incident:* torn zigzag seams on every model -- stranded orange tongues at
the fish's fin roots, speckled black on the cow's brow, colour crossing the
dragon's spikes mid-shape.
*Invariant:* labels live on the merge tree. After the recovery pass, and
again after verification and the sweep, the whole field is projected back
onto the base regions (area-majority per region), so every label edge the
paint stages see is a real edge (`segment3d.snap_to_base`). The single
exemption is a pattern painted onto smooth geometry, which has no region to
snap to; it is tracked, capped at pattern size, and its mask is trimmed to a
painter's silhouette rather than a stencil's teeth.

## 11. A proposer that is also its own judge

A stage that both FINDS a candidate and DECIDES it is real cannot be neutral,
because the framing that makes a thing findable is the framing that makes it
look like the answer. An aimed camera puts one candidate in the centre of a
tight frame and asks what is unmarked there; that is a leading question by
construction, in a way a wide orbit view asking "find every X" is not. Recall
bought that way is paid for in precision, silently, because the same stage
reports both.

*Incident:* the shell's aimed rounds took the barnacle index from 102 to 142,
and 34 of those were not barnacles -- mostly limpets, which share the family's
radius, relief sign and response strength exactly, plus a weed frond and a
patch of the rock's rim. Nothing in the geometry separates a limpet from a
barnacle; only looking does, and the stage that looked had already decided.
*Invariant:* proposing and keeping are separate stages with different framing.
The rounds propose; `index3d.confirm` shows each indexed instance tinted among
its neighbours -- framed at several instance widths, because a tight crop
destroys the very context that tells a cone on a rib from a cone on a frond --
and asks what the tinted shape actually is. The gate exits through selection
(see 6): the agent may name what the shape really is, and those names are the
finding, not the rejection. On the shell they named a whole second family the
index had been quietly mixing in.
*Watch for:* a stage whose recall number is reported by the stage that
produced it, and any gate whose "could not tell" and "was never shown" land in
the same bucket. The first confirm run read "125 kept, 81 unclear" when only 58
instances had ever been rendered to an agent -- a 21% rename rate among those
examined, published as 9%.
