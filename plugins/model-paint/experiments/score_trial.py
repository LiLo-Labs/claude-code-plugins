"""Classify click_trial.sh output into sensible / runaway / collapsed.

The trial's verdict was previously read off by eye, which makes "fewer than 2
failures out of 13" a judgement rather than a measurement, and makes two runs hard
to compare. This applies the same thresholds every time.

The bands come from the recorded baseline, not from taste: the 9 selections judged
sensible spanned 0.4-3.3% of the surface, the 2 runaways were 28.06% and 8.48%, and
the collapse was a single patch of 259 triangles. So >5% is a runaway with clear air
on both sides, and a single patch is a collapse regardless of its area.

A count is still not the answer. A selection can sit at a respectable 2% and have
its boundary in the wrong place, which no percentage reveals -- that is what the
renders are for. This narrows what to look at; it does not replace looking.

Usage: click_trial.sh <session> | python3 score_trial.py
"""

import re
import sys

RUNAWAY_SHARE = 5.0
COLLAPSE_PATCHES = 1

# "name: 46 patches, 25069 triangles, 1.76% of surface area"
LINE = re.compile(r"^(?P<name>.+?): (?P<patches>\d+) patches, "
                  r"(?P<triangles>\d+) triangles, (?P<share>[\d.]+)% of surface area")


def classify(patches, share):
    if patches <= COLLAPSE_PATCHES:
        return "collapsed"
    if share > RUNAWAY_SHARE:
        return "runaway"
    return "sensible"


def main():
    rows = []
    for line in sys.stdin:
        line = line.rstrip("\n")
        match = LINE.match(line)
        if match:
            rows.append((match.group("name"),
                         int(match.group("patches")),
                         float(match.group("share"))))
        elif line.strip() and not line.startswith("session "):
            # A refused selection (past --max-share) or an error still counts as an
            # outcome; silently dropping it would flatter the result.
            rows.append((line.strip(), None, None))

    if not rows:
        sys.stderr.write("score_trial: nothing to score on stdin\n")
        return 1

    counts = {"sensible": 0, "runaway": 0, "collapsed": 0, "refused": 0}
    for name, patches, share in rows:
        if patches is None:
            outcome = "refused"
            detail = ""
        else:
            outcome = classify(patches, share)
            detail = "%6.2f%%  %4d patches" % (share, patches)
        counts[outcome] += 1
        print("%-10s %s  %s" % (outcome, detail or " " * 20, name[:60]))

    failures = counts["runaway"] + counts["collapsed"] + counts["refused"]
    print()
    print("%d clicks: %d sensible, %d runaway, %d collapsed, %d refused"
          % (len(rows), counts["sensible"], counts["runaway"],
             counts["collapsed"], counts["refused"]))
    print("failures: %d of %d   (baseline 3 of 13; success is fewer than 2)"
          % (failures, len(rows)))
    print("now LOOK at the renders -- a sensible share can still be the wrong shape")
    return 0


if __name__ == "__main__":
    sys.exit(main())
