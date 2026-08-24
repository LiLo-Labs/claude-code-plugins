# Segmentation findings from the baby dragon

Measured against the user's real model (`Generic_Baby_Dragon_1.stl`, 475,270
triangles, flexi), not the synthetic fixture. The synthetic creature turned out to
be too easy: its horns are cones stuck onto a sphere, so they have a sharp crease
at the base. Real sculpted horns blend smoothly into the skull and no crease exists.

## What the model actually is

- 29 connected components, 25 of them substantial. This is a flexi chain: each
  component is one link. Component splitting is free, exact, and needs no tuning.
- Head is the component at the low-Y end of the chain: 29,264 triangles.
- Model midplane is X = 117.5; features mirror across it cleanly.

## Signal 1: dihedral crease cutting (threshold 35 degrees)

Finds features that meet the surface at an angle:

| region | faces | what it is |
|---|---|---|
| 689 / 682 | paired, dx +/-10.2 from midplane | the two eyes |
| 1796 | on the midplane, front | nose horn |
| 134 | zero thickness in Z | flat planar patch, an artifact, must be filtered |

Misses the two large swept-back head horns entirely: they leave 25,962 faces in
one undifferentiated skull region.

## Signal 2: shape diameter (local thickness), thin 22nd percentile

Ray-cast each face inward along its inverted normal; distance to the far wall is
the local thickness. With embreex this runs in well under a second for 29k faces.

Finds smooth protrusions that creases miss:

| region | faces | thickness | what it is |
|---|---|---|---|
| 532 / 511 | paired, dx +/-7.0, high Z | the two head horns (tips only) |
| 204 / 197 | paired, dx +/-8.8 | brow ridges |
| 186 / 180 | paired, dx +/-14.8 | ear/cheek spikes |
| 720 | midline, front | nose horn (agrees with the crease signal) |
| 2611, 560, 268, 247 | z ~ 16, interior | **false positives**: thin walls of the ball joint socket |

## Signal 3: mirror symmetry

Every real feature came back as a near-exact mirrored pair: matching face counts
(689/682, 532/511, 204/197, 186/180) at equal and opposite offsets from the
midplane. Pairing is both a strong anatomy hint and a validity check on the
segmentation itself. It also enforces the rule that paired features must always be
painted the same color.

## Open problems

1. **Thin-signal captures horn tips, not whole horns.** The base of a horn is
   thicker than the threshold so it stays with the skull. Needs region growing
   from each thin seed along increasing thickness, stopping at the neck (the local
   thickness minimum along the protrusion axis).
2. **Interior faces are false positives.** Ball joint sockets are thin walls and
   score exactly like a horn. Filter by casting a ray outward along the normal: if
   it hits the same component, the face is interior and not paintable anyway.
3. **Planar degenerate regions** (zero extent on an axis) should be dropped.

## Note on the two uploaded files

They are not the same geometry. The original has 475,270 faces in 29 components;
`4Color_Orca_Painted_v3_REPAIRED.stl` has 475,556 faces in 28 components, and
several components differ by tens of faces. The repair step altered the mesh and
merged or dropped a component. It is also rotated (bbox 153x153 versus 108x187).
Paint plans are not transferable between them by face index.
