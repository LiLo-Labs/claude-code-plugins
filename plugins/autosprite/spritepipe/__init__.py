"""AutoSprite: one character image in, an engine-ready sprite sheet out.

The pipeline is deliberately split into a part that judges and a part that draws,
and only the first one is allowed to be uncertain:

    vision  ->  names the character's parts and where they hinge     (rig.json)
    cutout  ->  cuts those parts out of the user's own pixels        (parts/)
    motion  ->  poses the skeleton over time                         (poses)
    render  ->  composites the posed parts, nearest-neighbour only   (frames/)
    pack    ->  lays the frames out                                  (sheet.png)
    atlas   ->  writes what every engine needs to read it            (*.json/.tres/.meta)
    verify  ->  proves the sheet still contains exactly those frames

Nothing in this package generates pixels. Every pixel in every output frame came
out of the image the user supplied, which is why `verify.py` can make the
guarantee it makes: the palette of the output is a subset of the palette of the
input, and the rest pose reconstructs the input exactly.
"""

__version__ = "0.1.0"
