"""Generate and rank many colour plans instead of hand-writing three.

Three options written by hand tend to be three variations on one idea. This
enumerates every legal assignment of filaments to parts, scores each one, and
returns a spread that is deliberately different from each other rather than the
top N of a single ranking -- which would all look alike.

Scoring is three things a painted model is actually judged on:

- **Chroma reach.** Area-weighted saturation. A palette of three neutrals and one
  accent produces a nearly grey model unless the accent lands on a large part, and
  no amount of rearranging neutrals fixes that. The score makes this visible
  rather than leaving the user to wonder why every option looks the same.
- **Boundary contrast.** Lightness difference across each pair of parts that touch,
  weighted by how much boundary they share. Two parts of similar value erase the
  feature between them at printed scale.
- **Detail salience.** Small parts must contrast with the part surrounding them, or
  they disappear. Eyes and barnacles are small on purpose; they are also the whole
  reason for painting the model.

When the loaded filaments cannot reach a decent chroma score, the report says so
and suggests which slot to swap. That is a real answer to "this looks flat", and
the user has four independent nozzles, so swapping is cheap.
"""

import argparse
import itertools
import json
import os
import sys


# --------------------------------------------------------------------------
# colour
# --------------------------------------------------------------------------

def hex_to_rgb(text):
    text = text.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError("not a hex colour: %r" % text)
    return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _linear(channel):
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb):
    """sRGB to CIE Lab (D65). Written out rather than pulled in as a dependency."""
    r, g, b = (_linear(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 1.00000
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1.0 / 3.0) if t > 0.008856 else (7.787 * t) + (16.0 / 116.0)

    fx, fy, fz = f(x), f(y), f(z)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def chroma(hex_colour):
    """Distance from the neutral axis in Lab. Grey, white and black score 0."""
    _, a, b = rgb_to_lab(hex_to_rgb(hex_colour))
    return (a * a + b * b) ** 0.5


def contrast(first, second):
    """Perceptual distance between two filaments."""
    one, two = rgb_to_lab(hex_to_rgb(first)), rgb_to_lab(hex_to_rgb(second))
    return sum((one[i] - two[i]) ** 2 for i in range(3)) ** 0.5


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

CHROMA_TARGET = 45.0        # roughly a saturated orange at full area
CONTRAST_TARGET = 60.0


def score_plan(assignment, parts, filaments, adjacency):
    """Score one {part_id: filament_index} mapping. Higher is better."""
    colours = {entry["index"]: entry["hex"] for entry in filaments}
    by_id = {part["id"]: part for part in parts}

    reach = sum(by_id[pid]["area"] * chroma(colours[slot])
                for pid, slot in assignment.items())
    reach = min(reach / CHROMA_TARGET, 1.0)

    boundary, weight = 0.0, 0.0
    for (left, right), share in adjacency.items():
        if left not in assignment or right not in assignment:
            continue
        gap = contrast(colours[assignment[left]], colours[assignment[right]])
        boundary += share * min(gap / CONTRAST_TARGET, 1.0)
        weight += share
    boundary = boundary / weight if weight else 0.0

    salience, small_weight = 0.0, 0.0
    host = max(parts, key=lambda part: part["area"])
    for part in parts:
        if part["id"] == host["id"] or part["area"] > 0.25:
            continue
        gap = contrast(colours[assignment[part["id"]]], colours[assignment[host["id"]]])
        importance = 1.0 / max(part["area"], 0.005)
        salience += importance * min(gap / CONTRAST_TARGET, 1.0)
        small_weight += importance
    salience = salience / small_weight if small_weight else 1.0

    return {
        "total": round(0.42 * reach + 0.30 * boundary + 0.28 * salience, 4),
        "chroma_reach": round(reach, 4),
        "boundary_contrast": round(boundary, 4),
        "detail_salience": round(salience, 4),
    }


def legal(assignment, parts, filaments, adjacency, min_distinct=3):
    if len(set(assignment.values())) < min(min_distinct, len(filaments)):
        return False
    colours = {entry["index"]: entry["hex"] for entry in filaments}
    for (left, right), share in adjacency.items():
        if share < 0.05 or left not in assignment or right not in assignment:
            continue
        if assignment[left] == assignment[right]:
            return False        # touching parts sharing a colour erase the boundary
    for part in parts:
        if part["area"] > 0.25:
            continue
        host = max(parts, key=lambda p: p["area"])
        if contrast(colours[assignment[part["id"]]],
                    colours[assignment[host["id"]]]) < 12.0:
            return False        # a small part invisible against its surround
    return True


def diverse(ranked, count):
    """Pick a spread, not the top N -- the top N are minor variations."""
    if not ranked:
        return []
    chosen = [ranked[0]]
    while len(chosen) < count and len(chosen) < len(ranked):
        best, best_distance = None, -1.0
        for candidate in ranked:
            if candidate in chosen:
                continue
            distance = min(
                sum(1 for pid in candidate["assignment"]
                    if candidate["assignment"][pid] != picked["assignment"][pid])
                for picked in chosen)
            merit = distance + candidate["score"]["total"]
            if merit > best_distance:
                best, best_distance = candidate, merit
        if best is None:
            break
        chosen.append(best)
    return chosen


def generate(parts, filaments, adjacency, count=9, min_distinct=3):
    slots = [entry["index"] for entry in filaments]
    ids = [part["id"] for part in parts]
    ranked = []
    for combination in itertools.product(slots, repeat=len(ids)):
        assignment = dict(zip(ids, combination))
        if not legal(assignment, parts, filaments, adjacency, min_distinct):
            continue
        ranked.append({"assignment": assignment,
                       "score": score_plan(assignment, parts, filaments, adjacency)})
    ranked.sort(key=lambda entry: -entry["score"]["total"])
    return diverse(ranked, count), len(ranked)


def swap_advice(filaments, best_reach):
    """What to load if the current set cannot get there."""
    if best_reach >= 0.45:
        return None
    neutrals = [entry for entry in filaments if chroma(entry["hex"]) < 12.0]
    if len(neutrals) < 2:
        return None
    victim = min(neutrals, key=lambda entry: abs(rgb_to_lab(hex_to_rgb(entry["hex"]))[0] - 50.0))
    return {
        "reason": ("the loaded set is %d neutral(s) and %d coloured filament(s), so "
                   "no arrangement of them produces a colourful model"
                   % (len(neutrals), len(filaments) - len(neutrals))),
        "swap_slot": victim["index"],
        "swap_name": victim["name"],
        "suggestions": [
            {"name": "teal", "hex": "#00A3A3"},
            {"name": "deep red", "hex": "#C81E28"},
            {"name": "sea blue", "hex": "#1F6FB4"},
            {"name": "moss green", "hex": "#4E7A39"},
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--parts", required=True,
                        help="JSON: {parts:[{id,name,area,neighbours:{id:share}}]}")
    parser.add_argument("--filaments", required=True, help="filament inventory JSON")
    parser.add_argument("--count", type=int, default=9, help="how many plans to offer")
    parser.add_argument("--output", required=True, help="directory for the plan JSONs")
    parser.add_argument("--min-distinct", type=int, default=3,
                        help="fewest different filaments a plan must use")
    args = parser.parse_args()

    with open(args.parts) as handle:
        document = json.load(handle)
    parts = document["parts"]
    adjacency = {}
    for part in parts:
        for other, share in (part.get("neighbours") or {}).items():
            key = tuple(sorted((part["id"], other)))
            adjacency[key] = max(adjacency.get(key, 0.0), float(share))

    with open(args.filaments) as handle:
        inventory = json.load(handle)
    filaments = [{"index": index, "name": entry["name"], "hex": entry["hex"],
                  "type": entry.get("type", "PLA")}
                 for index, entry in enumerate(inventory["filaments"], start=1)]

    plans, total = generate(parts, filaments, adjacency, args.count, args.min_distinct)
    if not plans:
        sys.stderr.write("palettes: no plan satisfied the rules; relax --min-distinct\n")
        return 2

    os.makedirs(args.output, exist_ok=True)
    names = {part["id"]: part["name"] for part in parts}
    default = max(parts, key=lambda part: part["area"])["id"]

    print("%d legal plans, offering %d" % (total, len(plans)))
    for position, plan in enumerate(plans, start=1):
        label = "plan-%d" % position
        payload = {
            "filaments": filaments,
            "default_filament": plan["assignment"][default],
            "assignments": [
                {"segment_id": pid, "filament": slot,
                 "reason": "%s in %s" % (names[pid], filaments[slot - 1]["name"])}
                for pid, slot in sorted(plan["assignment"].items())
                if pid != default],
            "_score": plan["score"],
        }
        path = os.path.join(args.output, label + ".json")
        with open(path, "w") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        summary = ", ".join("%s=%s" % (names[pid], filaments[slot - 1]["name"])
                            for pid, slot in sorted(plan["assignment"].items()))
        print("  %-8s score %.3f (chroma %.2f, contrast %.2f, detail %.2f)  %s"
              % (label, plan["score"]["total"], plan["score"]["chroma_reach"],
                 plan["score"]["boundary_contrast"], plan["score"]["detail_salience"],
                 summary))

    advice = swap_advice(filaments, max(p["score"]["chroma_reach"] for p in plans))
    if advice:
        print("\nnote: %s." % advice["reason"])
        print("      swapping slot %d (%s) for one of these opens up the palette: %s"
              % (advice["swap_slot"], advice["swap_name"],
                 ", ".join("%s %s" % (item["name"], item["hex"])
                           for item in advice["suggestions"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
