# Color planning

Four filaments in independent nozzles. No swaps, no purge tower, no waste per
color change - so the number of colors is not a budget. The budget is attention:
every color you add is one more thing the eye has to resolve. Use a fourth color
when it names a feature, not because it is free.

## Contrast, measured

"Reads from across the room" is luminance distance. Compute it rather than
guessing, and do it the same way every time:

```python
def luminance(hex_color):
    v = hex_color.lstrip("#")
    r, g, b = (int(v[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
```

| `abs(L_a - L_b)` | Reads as |
|---|---|
| >= 0.50 | strong - a 3 mm eye is visible across a desk |
| 0.25 - 0.50 | moderate - fine for large regions, weak on small ones |
| < 0.25 | weak - the boundary disappears at arm's length; only use it deliberately, for two large areas you want to read as one material |

Rank every loaded filament by distance from the base color. The top of that
ranking is reserved for the smallest high-salience features. Do not spend it on
a large region that would read fine at moderate contrast.

Hue difference does not rescue low luminance difference. Mid-red and mid-green
are both around L=0.3 and print as one grey shape in a photo.

## Thin geometry shifts color

- One or two perimeters of a light filament are translucent. White horn tips
  over a dark body pick up the body color and read grey-green.
- Dark filaments read flatter and slightly lighter on tips, because there is
  less material to absorb light and the layer lines catch highlights.
- Under about 2 mm of feature thickness, avoid white, pale yellow, and anything
  unsaturated. Saturated or dark filaments hold their color at small sizes.
- A light filament printed over a dark one bleeds at the boundary for a layer or
  two. On a tiny feature that boundary is most of the feature.

Net rule: **small features want the darkest or most saturated filament
available, not the lightest.** The exception is teeth and claws on a dark body,
where bone-white is the point - accept the bleed and say so.

## Building the plans

1. Rank regions by `area`. The largest is the base and becomes
   `default_filament`; leave it unassigned.
2. Group the named features. Every symmetric pair is one group. Every repeated
   set (spikes along a ridge, belly plates, all four feet) is one group.
3. Assign group by group, largest group first, checking after each: does this
   group share a color with a region it touches? If yes and the boundary is a
   real feature edge, change one of them.
4. Verify before emitting: every `symmetry_partner` pair has the same filament;
   every filament index used appears in `filaments`; no region got a color that
   is not loaded.

## Three plans, three characters

Offer 2-3 that differ in intent. These archetypes work on almost anything:

| Plan | Idea | Shape |
|---|---|---|
| **Natural** | Looks like an animal, not a toy | Base color everywhere; one secondary at moderate contrast on the large secondary features (belly, wings, horns); the high-contrast filament only on eyes. Often uses 3 of 4 filaments. |
| **High contrast** | Every feature reads from across the room | Base; strong-contrast secondary on all protruding features as one family; the remaining filament on the smallest features. Uses everything loaded. |
| **Single accent** | One color does all the work | Whole model in the base; exactly one feature family - horns, or eyes, or the ridge - in the strongest contrast filament. Two filaments, maximum impact, cheapest to be wrong about. |

For a non-creature, the same three become: matching trim (natural), panel/trim/
text all separated (high contrast), and body plus one highlighted element such
as the text or the moving part (single accent).

Present them as three named looks with a one-line description each, in feature
words. No ids, no numbers.

## Worked example

Sample creature: body sphere, two eyes, two horns. Loaded: 1 Slate Grey
`#4a5058` (L=0.31), 2 Bone White `#e8e0cf` (L=0.88), 3 Black `#1a1a1a` (L=0.10),
4 Copper `#b06b2c` (L=0.46).

Distances from the base (slate, L=0.31): bone 0.57 strong, black 0.21 weak,
copper 0.15 weak.

- **Natural**: body slate, horns copper (0.15 - deliberately quiet, the horn
  reads by its shape, not its color), eyes black. Two accents, subdued.
- **High contrast**: body slate, horns bone (0.57), eyes black. Copper stays in
  its nozzle: this model has only two feature families, and a fourth color would
  have to be painted onto something that is not a feature. Leaving a loaded
  filament unused is a valid plan; inventing a region to justify it is not.
- **Single accent**: body slate, horns and eyes both bone. One decision, reads
  from three meters.

Notice black scores weak against slate but still works for eyes: contrast rules
apply to the region's *neighbor*, and an eye's neighbor is the body. When a
feature would fail its own test, either move it to a stronger filament or say in
the reason that it is intentionally subtle.
