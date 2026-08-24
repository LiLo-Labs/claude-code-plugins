"""Turn overlapping selections into a partition: every triangle in exactly one part.

Selections are made independently -- by different agents, or by one agent working
through a feature list -- and independent selections overlap. Measured on a real
model: 24 selections left 24.6% of the surface in no part at all and 26.9% claimed
by two or more, some by six. Painting from that pile is not painting a plan; it is
painting whichever selection happened to be applied last, with a quarter of the
model falling through to a default that is right only by luck.

Two rules resolve it:

**Specific beats general.** Where parts overlap, the smaller one wins. Someone who
selected "barnacle cluster" inside a region already covered by "shell body" meant
the cluster, every time. Explicit --priority overrides this when the default
reading is wrong.

**Nothing falls through silently.** Whatever no part claims has to go somewhere,
and the choice matters more than it looks. Sending all of it to one named part is
wrong whenever the leftover is spread across the model: on a shell standing on a
rocky base, 42% of the base was unclaimed, and a single fallback of "shell body"
painted half the rock as shell.

So the default is `--fill nearest`: unclaimed faces adopt the label of the nearest
assigned face, spreading outward across the surface itself rather than through
space. A gap inside a barnacle field becomes barnacle; a gap in the rock becomes
rock. `--fallback NAME` remains available for the case where one part genuinely
should absorb everything left.

Output is a label per triangle plus a coverage report that is checkable rather
than reassuring: it states the leftover share and what was taken from whom.
"""

import argparse
import json
import os
import sys

import numpy as np


UNASSIGNED = -1


def resolve(parts, face_count, priority=None):
    """Assign each face to exactly one part. Returns (labels, order, stolen)."""
    order = list(range(len(parts)))
    if priority:
        rank = {name: index for index, name in enumerate(priority)}
        # Named parts first in the order given; everything else after, by area
        # descending so the general ones are laid down before the specific.
        order.sort(key=lambda i: (rank.get(parts[i]["name"], len(rank)),
                                  -parts[i].get("area", 0.0)))
    else:
        order.sort(key=lambda i: -parts[i].get("area", 0.0))

    labels = np.full(face_count, UNASSIGNED, dtype=np.int32)
    stolen = {}
    for position in order:
        indices = np.asarray(parts[position]["face_indices"], dtype=np.int64)
        indices = indices[(indices >= 0) & (indices < face_count)]
        previous = labels[indices]
        taken = previous[previous != UNASSIGNED]
        if taken.size:
            for victim, count in zip(*np.unique(taken, return_counts=True)):
                key = (parts[int(victim)]["name"], parts[position]["name"])
                stolen[key] = stolen.get(key, 0) + int(count)
        labels[indices] = position
    return labels, order, stolen


def fill_nearest(labels, pairs):
    """Grow every assigned region outward at equal speed until nothing is left.

    A multi-source breadth-first sweep over the face graph, so a gap is filled by
    whatever actually borders it. Distance is measured along the surface, which is
    what matters here: a face inside a crevice should take the crevice's part, not
    whatever happens to be near it in straight-line space on the other side of a
    wall.
    """
    labels = labels.copy()
    count = len(labels)
    adjacency = [[] for _ in range(count)]
    for left, right in pairs:
        adjacency[left].append(right)
        adjacency[right].append(left)

    frontier = [face for face in range(count) if labels[face] != UNASSIGNED]
    while frontier:
        nxt = []
        for face in frontier:
            value = labels[face]
            for neighbour in adjacency[face]:
                if labels[neighbour] == UNASSIGNED:
                    labels[neighbour] = value
                    nxt.append(neighbour)
        frontier = nxt
    return labels


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--parts", required=True, action="append",
                        help="parts.json to include; repeat to merge several")
    parser.add_argument("--session", required=True, help="session.npz for face count and areas")
    parser.add_argument("--output", required=True, help="path for the resolved parts.json")
    parser.add_argument("--fallback", default=None,
                        help="one part absorbs everything unclaimed (rarely right)")
    parser.add_argument("--fill", default="nearest", choices=["nearest", "none"],
                        help="nearest: unclaimed faces adopt the closest assigned "
                             "part across the surface. none: leave them unassigned")
    parser.add_argument("--priority", default=None,
                        help="comma-separated part names, laid down first to last")
    parser.add_argument("--max-leftover", type=float, default=2.0,
                        help="fail if this %% of area is unclaimed and no --fallback")
    args = parser.parse_args()

    session = np.load(args.session)
    areas = session["areas"]
    face_count = len(session["faces"])

    parts, seen = [], {}
    for path in args.parts:
        if not os.path.exists(path):
            parser.error("no such file: %s" % path)
        with open(path) as handle:
            for part in json.load(handle).get("parts", []):
                name = part["name"]
                if name in seen:      # same name from two files: union them
                    merged = sorted(set(seen[name]["face_indices"]) | set(part["face_indices"]))
                    seen[name]["face_indices"] = merged
                    continue
                seen[name] = dict(part)
                parts.append(seen[name])
    if not parts:
        parser.error("no parts found in %s" % ", ".join(args.parts))

    for part in parts:
        indices = np.asarray(part["face_indices"], dtype=np.int64)
        part["area"] = float(areas[indices[(indices >= 0) & (indices < face_count)]].sum()
                             / areas.sum())

    priority = [name.strip() for name in args.priority.split(",")] if args.priority else None
    labels, order, stolen = resolve(parts, face_count, priority)

    leftover = labels == UNASSIGNED
    leftover_share = float(areas[leftover].sum() / areas.sum()) * 100.0

    if leftover.any() and args.fill == "nearest" and args.fallback is None:
        labels = fill_nearest(labels, session["pairs"])
        leftover_after = labels == UNASSIGNED
        print("  filled by nearest part     : %.2f%% of area"
              % (leftover_share - 100.0 * float(areas[leftover_after].sum() / areas.sum())))
        leftover = leftover_after

    if leftover.any():
        if args.fallback is None and args.fill == "none":
            if leftover_share > args.max_leftover:
                sys.stderr.write(
                    "resolve: %.2f%% of the surface is in no part and no --fallback "
                    "was given.\nThat share would silently take the default filament. "
                    "Name a fallback part, or select the missing regions first.\n"
                    % leftover_share)
                return 2
        else:
            match = [i for i, part in enumerate(parts) if part["name"] == args.fallback]
            if not match:
                parser.error("--fallback %r is not one of the parts" % args.fallback)
            labels[leftover] = match[0]

    print("resolved %d parts over %d triangles" % (len(parts), face_count))
    print("  unclaimed before fallback : %6.2f%% of area" % leftover_share)
    if args.fallback:
        print("  absorbed by               : %s" % args.fallback)
    print("  every triangle assigned    : %s"
          % ("yes" if not (labels == UNASSIGNED).any() else "NO"))

    if stolen:
        print("\noverlaps resolved (specific beats general):")
        for (victim, winner), count in sorted(stolen.items(), key=lambda kv: -kv[1])[:12]:
            print("  %7d faces  %-34s -> %s" % (count, victim[:34], winner[:34]))

    resolved = []
    print("\nfinal partition:")
    for position, part in enumerate(parts):
        indices = np.where(labels == position)[0]
        share = float(areas[indices].sum() / areas.sum()) if len(indices) else 0.0
        resolved.append({"name": part["name"], "faces": len(indices),
                         "area": round(share, 5),
                         "face_indices": [int(v) for v in indices]})
        if len(indices):
            print("  %-46s %7d faces  %6.2f%%" % (part["name"][:46], len(indices), 100 * share))
    empty = [part["name"] for part, entry in zip(parts, resolved) if not entry["faces"]]
    if empty:
        print("\n  fully absorbed by more specific parts: %s" % ", ".join(empty))

    with open(args.output, "w") as handle:
        json.dump({"parts": [entry for entry in resolved if entry["faces"]]}, handle, indent=2)
        handle.write("\n")
    print("\nwrote %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
