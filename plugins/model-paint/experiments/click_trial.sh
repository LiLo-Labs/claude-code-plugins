#!/usr/bin/env bash
# The click trial: 13 features on the scallop shell, one click each, and the number
# that decides whether local selection is usable.
#
# The baseline to beat, at tolerance 0.30 with no edge blocking: 9 sensible,
# 2 runaway ("front left flank rib band" reached 28.06% of the surface, "barnacle
# boulder" 8.48%) and 1 collapsed to a single patch. Roughly seven clicks in ten.
# Success is fewer than 2 failures out of 13, ideally 0.
#
# Usage: click_trial.sh <session-dir> [tolerance] [respect-edges]
#
# The session argument exists because this script used to hardcode a path into a
# scratchpad that no longer exists, which made the trial unrunnable. The pixel
# coordinates below are specific to the shell model and its 7 rendered views, so
# they only mean anything against a session built from that model.
#
# Read the percentages, then LOOK at <session>/selections/*.png. A number in range
# is not the same as a boundary in the right place.
set -uo pipefail

SESSION="${1:?usage: click_trial.sh <session-dir> [tolerance] [respect-edges]}"
TOLERANCE="${2:-0.30}"
RESPECT_EDGES="${3:-1000}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "session $SESSION | tolerance $TOLERANCE | respect-edges $RESPECT_EDGES"

python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at front:506,549 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Shell-to-base undercut and deep shadow pockets" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at iso:518,274 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Barnacle colony - upper whorl rib band" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at front:324,292 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Crack-line network across the whorl" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at iso2:571,647 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Barnacle boulder at the shell foot" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at front:291,377 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Barnacle patch - front left flank rib band" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at right:394,280 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Torn break edges and shard rims" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at front:696,543 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Barnacle patch - lower right of the coil centre" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at front:399,267 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Open barnacle apertures" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at back:297,399 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Barnacle patch - mid flank rib band" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at iso2:295,96 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Ribbed limpet caps on the far shoulder" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at left:327,574 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "Barnacle spat band in the rib groove" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at front:456,508 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "barnacle cluster left of coil centre" --replace 2>&1 | head -1
python3 "$HERE/scripts/patch_select.py" --session "$SESSION" \
    --at front:484,547 --grow local --tolerance "$TOLERANCE" \
    --respect-edges "$RESPECT_EDGES" \
    --name "barnacle cluster below coil centre" --replace 2>&1 | head -1
