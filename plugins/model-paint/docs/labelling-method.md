# The labelling method

How to turn a model nobody has seen into a named, addressable, paintable map of its
surface. This is the abstract statement of the loop: what is computed mechanically,
what has to be judged by looking, what a human names, and what is verified before
anything is painted.

Read `docs/agentic-process.md` first — it says why the loop has this shape.
This document says what the loop *is*. Every rule below carries the measurement that
forced it, and where a rule is not yet earned it says so instead of asserting it.

## 0. What has actually been shown, and on what

Two models. `samples/scallop-shell-barricade.stl` — 626,766 triangles, **one**
connected body, entirely sculpted, nothing crease-bounded — and
`samples/baby-dragon.stl` — 475,270 triangles, 29 separate bodies, sharp creases.
Nothing here has been run on a third model.

Three independent implementations of the grouping step were written and cross-checked
against each other (`scripts/level0_basis.py`, `scripts/level0_connect.py`,
`scripts/level0_multiscale.py`). Every one of them beats the recorded baseline failure
on the shell. **Every one of them fails to produce the same partition twice.** The
honest summary is therefore not "here is the method that works" but:

- **What works, reproducibly, on both models:** the partition property (§4), the
  coordinate handle (§5), and — given a parent region that is already one thing —
  **subdividing it at the rung its own scale profile picks** (§2). That last one is
  the strongest result in the project and it is a *level ≥ 1* result.
- **What does not work:** choosing the number of regions (§3), and getting the same
  answer twice from the same model (§9).
- **What is not known:** whether any of it generalises past these two shapes.

Do not read a number in this document as a property of the method. Read it as a
property of a named run on a named model, which is all any of them are.

## 1. The loop

```
 build   session  -> views, fields, view atlas                 mechanical
 build   ladder   -> patches at several rungs                  mechanical
 -------------------------------------------------------------------------
 pick    rung     -> which zoom level this level of the tree is HUMAN, by looking
 group   patches  -> candidate regions                         mechanical
 pick    k        -> how many regions                          HUMAN, by looking
 render  regions  -> one flat colour each                      mechanical
 LOOK    at it    -> is each region one thing?                 HUMAN, required
 name    regions  -> "umbilicus", "limpet cap", ...            HUMAN, required
 verify           -> coverage, controls, falsifiers            mechanical
 -------------------------------------------------------------------------
 for each named region that is one thing but has parts:
     compute its own rung from its scale profile               mechanical
     recurse
```

The mechanical steps are cheap and repeatable. The three human steps are the ones
that were attacked hardest and survived; §8 says why each is still there.

## 2. The level a feature belongs to is *determined*, not chosen — below level 0

**The rule.** A patch scale is a zoom level, and a feature is only cleanly separable
near its own scale. Measured, on one model, in both directions at once: the shell's
front-left-flank barnacle band is clean at rung 400 and shatters at 12,800, while the
upper-whorl colony is clean at 12,800 and only partly found at 400. A complete
inversion between two features on one model, so no single rung serves both, and a
hierarchy is not a convenience — it is the only structure that can hold both answers.

**How a child's rung is computed.** Build a scale space over the mesh: iterated
umbrella smoothing at k = 3, 6, 12, 24, …, and at each k take the high-pass — the
displacement of the surface from its smoothed copy along the vertex normal. Stop when
the area-weighted mean |displacement| exceeds one mean edge length. That stop rule has
two mesh quantities in it and no fraction: shell k = 3..48, dragon k = 3..24.

For any region, its log-ratio profile `lr_k = log(mean |v_k| over the region) −
log(the same over the whole model)` peaks at the scale its relief actually lives on.
Convert that peak to a radius (`sqrt(k) × mean_edge`) and take the built ladder rung
whose median patch radius is closest. No rung is passed in.

**The evidence, and I looked at it.** Subdividing the shell's barnacle region at the
rung its own profile picked — 12,800, computed — puts orange in the aperture of
nearly every barnacle cone on the model, purple on the cone flanks, and a blue collar
around each. Everything outside the parent is grey, so the subdivision stayed inside
its parent. That is exactly the case `label_tree.py` was written around — *"the
barnacle apertures are black" is the same instruction one level down* — with the zoom
level derived rather than guessed. `wf/multiscale/shell/labels/multiscale-region-4-iso.png`.

**Where this fails, stated plainly.** The mechanism only works *below* level 0.
Level 0's own rung is not computed by anything: in the one implementation that claims
to have eliminated it, `rung = sorted(ladder_*.npy)[0]` — a directory listing. Remove
`ladder_400.npy` from a dragon session and level 0 silently runs at 1,600 and returns
a partition of **ARI 0.080** against the default. The parameter was not removed, it
was moved into the filesystem where it is invisible. On the shell, rung 400 vs 800
gives ARI 0.265.

And the recursion inherits its parent. The barnacle-aperture result is good *because
level 0 handed it a coherent parent*. On the dragon, level 0 never produces one, and
subdividing the 22%-of-area dorsal class at its computed rung gives scattered orange
and purple fragments across individual scales rather than "scale tip".

**So: the rung is derived for every level except the first, where a human still picks
it by looking at a contact sheet.** That is the honest state.

## 3. Region count: three attempts, no solution

This is the open failure, and it is worth being exact about how it failed, because
the shapes of the three failures are different and all three are instructive.

| attempt | rule | what it really depended on |
|---|---|---|
| stability gate | largest k whose k-means agreement clears 0.90, with a 1%-of-area floor | on the shell the gate is **inert** (0.85 → 0.99 all give k=6); on the dragon it is **decisive** and clears by 0.004 (k=5 scores 0.904; at gate 0.91 it collapses to k=2) |
| stability argmax | argmax of cross-restart reproducibility over `range(4, 21)` | the **literal 4**. Reproducibility rises monotonically as k falls (k=2 is a perfect tie, 1.00, every time), so the argmax always sits at the bottom of whatever range it is handed. Extend to `range(2, 21)` and it returns k=2 on both models |
| honest refusal | none — ship a k-sweep contact sheet | measured reseed-ARI flat at 0.21–0.27 across k = 4..14 with its maximum at k=3, and BIC decreasing monotonically to the edge of a k = 2..16 sweep. Concluded no available statistic picks k, and said so |

The third is the only one that is not fooling itself.

**And k dominates the method.** My own measurement, on the falsifier of §7: on the
dragon at k=4, *every* implementation including the **unmodified baseline** scores 3
of 4 on the repeated-part test; the same baseline at k=10 scores 0 of 4.

```
  baseline label_tree.py   k=10   dominant 0/4   mean overlap 0.590
  baseline label_tree.py   k=4    dominant 3/4   mean overlap 0.797
  basis    k*=5 (seed 7)          dominant 1/4   mean overlap 0.774
  basis    k*=5 (seed 11)         dominant 2/4   mean overlap 0.866
  connect  k=4                    dominant 3/4   mean overlap 0.780
  connect  k=6                    dominant 2/4   mean overlap 0.488
  connect  k=8                    dominant 2/4   mean overlap 0.497
  multiscale k=10                 dominant 1/4   mean overlap 0.501
```

Read that table twice. The spread within one method across k is larger than the
spread across methods at fixed k. **The open problem is not a better descriptor
space. It is that k is doing most of the work and nothing measured here can choose
it.** Any future attempt that reports a win without holding k fixed has not reported
anything.

**What to do until it is solved.** Render the candidate k side by side in one contact
sheet, in a fixed reading order, and pick by looking — the same instrument that picks
the rung, for the same reason. But hold it to its own standard: on the shell, a
shortlist of k = 2 / 4 / 6 is *not* three choices — k=2 is the model in one colour
plus its invisible underside and k=4 adds one cap. A shortlist whose entries are a
ramp should be reported as a ramp.

## 4. The partition is total and disjoint by construction, and that includes what no camera sees

**Why it is enforced rather than hoped for.** Independent selections measured 24.61%
of the surface in no part and 26.86% claimed by two or more, one region contested by
six. Painting from that pile means whichever selection was written last wins.

**How it is guaranteed.** The chain from a face to its label is a composition of total
functions and nothing else:

```
 face -> patch      total: the segmenter labels every face
 patch -> group     total: clustering assigns every live patch exactly one group
 group -> region    total: one region node per group
```

A level is built by clustering *all* of the parent's patches, so coverage is total
before anything is rendered. A subdivision only ever partitions its parent's own
faces, so a child cannot reach outside its parent. The handful of faces stranded at a
parent boundary — a patch straddling the edge — go through `fill_nearest` **across the
surface graph**, never through a global default: a single global fallback once painted
42.4% of the rock base as "shell body".

Verified rather than asserted: re-walk every node's `face_indices` and count. Shell
626,766 / 626,766 faces, 0 unlabelled, 0 in two regions. Dragon 475,270 / 475,270,
0 and 0. Both hold on every implementation, at every rung and every k I have seen,
and both hold for subdivisions. **This is the one property that never broke.**

**Faces no camera can see.** The shell's view atlas over 32 Fibonacci directions
sees 89.28% of faces from at least one direction, median 4 — and **67,171 faces
(10.72%) from none**. Interior and enclosed geometry can only ever be coloured by
inheriting a label.

The rule that follows: **labels come from the mesh, so hidden faces are labelled
exactly like visible ones — but they cannot be *verified* like visible ones, and the
report must say which is which.** On the shell the flat printed underside came out as
its own region every time (10.12% of area in 2,465 faces in one run; 9.61% in
another), correctly isolated as one nameable thing — a flat cut face — and correctly
reported as *never visible from any stored view* instead of being given a bogus
coordinate. Note also what that costs: in one default run, 16.7% of the model's area
and 2 of its 6 paint regions were spent on geometry no camera in the session can see.
That is not a bug, but a report that does not say it is a bad report.

## 5. A label needs a coordinate that survives more than one angle

A name without a handle is not addressable, and a centroid is not a handle — the
centroid of a band wrapping a whorl sits *inside* the model.

**How the handle is computed.** Walk the stored views (front, back, left, right, top,
iso, iso2), test the region's faces against each view's pick buffer, keep the view
that sees the most of the region, and return the median hit pixel as `view:x,y`. The
coordinate is therefore guaranteed to be a pixel where that region is actually the
front-most surface, in the view that sees most of it — which is what "valid from
multiple angles" has to mean on a closed 3D surface. There is no single pixel valid
from all angles; the honest object is *the view that sees the region best, plus how
much of the region that view sees*.

**So report the fraction, not just the pixel.** Per node, `visible_area_fraction`:
shell median 99.4%, least-visible instance 42.8%. A node under ~0.5 has a coordinate
that points at a minority of itself and a human correcting by name should be told so.

**Two measured faults to carry forward.** The visibility search truncates its face set
to the first 200,000 members, so a region larger than that (shell region-0, 280,052
faces) gets a coordinate drawn from a subset. And a "not visually verifiable"
threshold set at 0.10 — chosen far under the observed floor of 0.428 so that it could
not fire — fired 0 times on the shell and 4 times on the dragon, every one of them a
degenerate 4-face sliver body of 0.0000% area. **A threshold that is either silent or
reporting mesh artefacts has never been tested.** Set it where it can fail, or drop it.

**Coordinates never appear in anything shown to the user.** They are the agent's
handle for rendering and cross-checking; corrections are by name.

## 6. A metric is evidence only after a deliberately worthless control has lost to it

This is the rule this round paid for, and it is the most transferable thing here.

One implementation defended its feature space with a held-out falsifier: re-run the
segmenter at three unseen seeds, cluster at fixed k, and measure area-weighted ARI
between the resulting face-level maps. New space 0.293 / 0.415 at k = 10 / 6 against
the old space's 0.133 / 0.172 — a 2.2–2.7× margin over the stated kill threshold. The
numbers are real; I reproduced them exactly.

Then run the *same code path* on the *same held-out seeds* with a space that is the
patch's area-weighted mean X, Y, Z centroid and nothing else:

```
  space         k=4     k=6     k=10
  basis        0.582   0.415   0.293
  coords_xyz   0.582   0.472   0.487     <- ties at k=4, WINS at k=6 and k=10
  raw_fields   0.338   0.287   0.274
  old          0.214   0.172   0.133
```

**I rendered `coords_xyz` at k=6 and looked at it.** It is four geographic wedges —
gold upper hemisphere, red one lower quadrant, green another, teal slivers — cutting
straight through the ribs, the panels, the barnacle colonies and the rock base
indiscriminately. It is the worst part map available and it beats the space it was
supposed to falsify by 1.66× at k=10.

The mechanism is obvious once seen: every channel of the defended space is a *per-face
field*, and only the pooling depends on the segmentation. Re-seeding the segmenter
re-pools the same fields, so the score is high for the same reason a constant field
would score 1.0. **Reseed-ARI measures "is your descriptor a face field rather than a
cell statistic". It does not measure whether the part list is any good.**

The rule: **before a statistic is allowed to be evidence, show it ranking a
known-bad partition below a known-good one.** Two controls cost about four lines each
and would have caught this before the conclusion was drawn. Run them first, not after
an adversary asks.

The corollary rule from `docs/agentic-process.md` still stands above this one and is
what caught the rest: **render it and look.** Numbers that flattered the work and were
contradicted by the image, this round: an ablation with the best panel score in the
set (dominant 0.56 vs 0.37) whose render is one class covering 42.18% of the model
holding the panels *and* the base rock *and* a barnacle colony together; a variant
reaching the highest panel dominance measured (58%) by absorbing the ribs into the
panel; and one report describing its own render as "teal is the ribs" when the ribs in
that image are purple, the same class as the panel. All three would have shipped on
the metric.

## 7. The falsifiers that are generic, and what each one costs

A falsifier the method chose for itself is not a test. These three are subject-free
and can be built on a model nobody has seen.

**Repeated congruent bodies — free, decisive, and not always available.** Find
connected components; for each, its surface area and the eigenvalues of its
area-weighted centroid covariance. Two bodies matching on both to several significant
figures are literally the same object twice, found with no subject knowledge. On the
dragon this returns exactly four mutual pairs, separated from every other pairing by
about three orders of magnitude:

```
  areas 894.004/894.035, 1205.162/1205.112, 1034.330/1034.324, 1046.375/1046.357
  best non-pair score 2.1e-01 against the pairs' 2.8e-04 .. 2.5e-03
```

A method that groups "kinds of thing" must label them the same. Scoring is the table
in §3. **Cost: it requires repeated geometry.** The shell is one connected body with no
repeated part, so this test is simply unavailable there — which is exactly why the
hard case is the hard case.

**Mirror symmetry — available whenever the model has a plane.** Reflect, match faces,
score chance-corrected agreement of the label map with its own reflection. On the
dragon the plane is real (median reflected residual 0.00134 of the diagonal, 99.99% of
faces matched) and it separates methods: kappa 0.655 / 0.576 / 0.601 at k = 4/6/8
against the baseline's 0.474 / 0.469. **Cost: it is satisfied by wrong answers.** Every
reseeded variant scores just as well — 0.610 on a re-tessellation, 0.664 at a
different k-means seed — while being a mutually contradictory partition. Symmetry
measures plausibility, and plausibility is not reproducibility. A chiral model (the
shell is a spiral) has no plane at all.

**Hand-clicked landmarks — the only one that works on any model, and the only one
that costs a human.** Click pixels on grid-overlaid views, render the picks back and
prune the ones that landed wrong, then score pairwise grouping agreement, chance
corrected. This is what produced the ground truth the whole round was scored against
(34 smooth-panel patches, 8 rib, 16 barnacle, 8 coral on the shell; 20 shell and 14
dragon landmarks for the reseed test). **Cost: an hour, and it must itself be
verified by looking** — 5 rib clicks had to be dropped because panel clicks landed in
the same patch, which is itself a finding: at rung 400 a patch already straddles rib
and panel.

Run at least one of the three before believing any partition. Where none is
available, say that no falsifier was available rather than substituting an internal
statistic (§6).

## 8. Where a human is required, and where one is merely convenient

**Required — picking the rung at level 0.** Not a gap in the tooling; measured to be
undecidable from the available statistics. On the shell's flank ladder the same click
gives 0.94% at rung 400, 0.32% at 1,600 and 0.30% at 6,400 — all three inside the
sensible band, and only 400 is the whole feature; the others are fragments of it.
Area cannot pick the rung. A contact sheet can, in about two seconds of looking.

**Required — picking k.** §3. Three attempts, two of which were decided by a constant
with no margin.

**Required — naming.** No script here invents a name and none should. Vocabulary is
derived from what is seen: "umbilicus", "limpet cap", "shell shard", "faceted inner
panel" — none of which any hardcoded anatomy list would have held. Regions keep a
`region-N` placeholder until someone names them, and an unnamed region is visible as
unnamed rather than quietly folded into a neighbour.

**Required — confirming the part list before any colour.** The user's own correction,
and it reordered the pipeline: arguing about colour is wasted if the part list under
it is wrong. Iterate by name — rename, merge, split, add what was missed, show me
part 7 — answering each with an updated render.

**Merely convenient — everything else.** The contact sheets, the shortlist, the
per-region isolation renders, the printed areas and coordinates. These make the four
required judgements fast; none of them makes a judgement.

**And one thing a human must *not* be asked for:** anything subject-specific in the
code. A workflow whose lenses hunt "barnacle clusters" is a script for one model. It
was written that way once and thrown away.

## 9. What is still broken

**Nothing here produces the same partition twice.** Re-tessellate the same model at
the same rung with a different segmenter seed, re-derive everything, cluster at the
same k, and the answer does not survive: dragon area-weighted ARI **0.130**, shell
**0.193**; best one-to-one matched area 0.492 and 0.447. Hand-picked landmark grouping
agreement is **at chance** — −0.084 on 14 dragon landmarks, 0.052 on 20 shell
landmarks. The baseline scores the same (shell 0.178 / −0.023), so this is inherited,
not introduced — which makes it the field's problem and not one implementation's. The
partition described in any report is a property of that *run*, not of the model.

**And the renders cannot detect it.** Each run produces an equally plausible, equally
symmetric, mutually contradictory answer; a dragon toe class present in one run is
absorbed into the body class in the next. Looking is necessary and it is not
sufficient here. It took two runs and a comparison.

**Unifying the smooth panel and keeping the ribs are in tension.** On the shell the
recorded failure is that one continuous smooth panel is split across three clusters
(measured worse than recorded: 34 ground-truth panel patches across **9 of 10**
clusters, perplexity 7.57, largest cluster holding 19% of the panel's area, and 28 of
31 touching panel-panel pairs assigned to different clusters — there is no boundary in
the wrong place, there is no boundary at all). The best result fixes it: panel
dominance 0.38 → 0.68 at k=6, perplexity 4.61 → 2.63, touching-pair disagreement
0.77 → 0.48, and I looked — the inter-rib panels and cracked plates come out as one
purple class with no confetti. **It pays for it with the rib.** Per-class dominance
hides this; the overlap between two classes' cluster distributions does not: panel/rib
overlap 0.54 → **0.88**, where the rib's dominant cluster *is* the panel's. A rib
scoring dominance 0.80 while sitting 80% inside the panel class is why "it improved"
is not a result. A second, independent implementation measured the same tension
systematically: whenever panel dominance is high, panel and rib are merged; whenever
they are distinct, panel dominance is ≤ 0.43.

**The diagnosis for the rib, and where the next attempt should go.** The old
`extent` / `elongation` descriptors are the *bounding box of a SLIC cell*: across
segmenter seeds, elongation reproduces at r = **0.261** and extent at 0.465, against
curvature 0.785 and roughness 0.736. They are the segmenter's coin flip, they supply
51.7% of the force splitting the panel, and yet `extent` cannot simply be dropped —
it is the only descriptor that says a rib is long, and removing it makes the panel
*worse* (perplexity 7.24 → 8.68). Replacing them with anisotropy read off a geodesic
ball loses the rib entirely, because a broad rounded cord on an already-curving
surface has much the same normal spread as the panel beside it. Adding more radii
does not fix it (four probes, panel/rib overlap stays 0.76–0.90). **What is missing is
a directional statistic — the covariance eigenvector, not its eigenvalues — measured
on the surface rather than on the cell.** That is the next experiment, and it is
stated here so it is not re-derived.

**A single rung gives a nameable answer on one rung per model, not on the ladder.**
Same command, only `--rung` changed, automatic k: shell k\* = 6 / 4 / 2 at rungs
400 / 1600 / 6400; dragon 5 / 2 / 2. Four of those six are the whole model in one
colour plus a sliver. Since the project's own central finding is that no single rung
serves all features, "it works at rung 400" is a rung result, not a method result.

**Names do not carry between rungs.** At fixed k, shell rung 400 vs 1600 gives ARI
0.296. The part list a human is asked to name and correct is as much a function of the
rung as of the model.

**Descriptor channel lists are shell-fitted and fragile.** In one shipped six-channel
space, dropping a single channel moves the shell partition to ARI 0.429 — *lower*
agreement than the reseed-ARI 0.449 the space is defended by. In another, the
hand-picked 3-of-6 subset is the argmax of eight candidate spaces on the shell and
fourth of eight on the dragon, where deleting the contribution entirely scores better
than shipping it (0.618 vs 0.600). A design-time choice with more leverage on the
output than the noise the design is written to resist is not a settled choice.

## What "done" would mean

An agent is handed a model it has never seen. It builds a session and a ladder, looks
at one contact sheet and picks a rung, looks at one shortlist and picks k, renders the
regions and names them, and reports a partition that is 100% covered, disjoint,
coordinate-addressable, and **the same partition the next run produces**. Then it
subdivides each named region at the rung that region's own scale profile picks, and
the names one level down are as good as the barnacle apertures.

Everything in that sentence exists today except the clause in bold and the two picks.
That is the gap, and it is three measurements wide: ARI 0.130 on a reseed, k\* = 6/4/2
across three rungs, and a stability metric that a spatial Voronoi wins 0.487 to 0.293.
