#!/usr/bin/env bash
# The click trial again, run through the Monte Carlo consensus selector.
#
# Same 13 features and same clicks as click_trial.sh, so the two are directly
# comparable. What changes is what bounds the selection: instead of one growth on
# one segmentation, each click is grown across every draw in the ensemble and kept
# where the draws agree.
#
# Usage: mc_trial.sh <session-dir> [tolerance] [threshold]
#
# Needs mc_ensemble.py to have been run against the same session. The coordinates
# are specific to the shell model and its 7 rendered views.
set -uo pipefail

SESSION="${1:?usage: mc_trial.sh <session-dir> [tolerance] [threshold]}"
TOLERANCE="${2:-0.30}"
THRESHOLD="${3:-0.5}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "session $SESSION | tolerance $TOLERANCE | threshold $THRESHOLD"

python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at front:506,549 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Shell-to-base undercut and deep shadow pockets" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at iso:518,274 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Barnacle colony - upper whorl rib band" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at front:324,292 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Crack-line network across the whorl" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at iso2:571,647 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Barnacle boulder at the shell foot" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at front:291,377 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Barnacle patch - front left flank rib band" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at right:394,280 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Torn break edges and shard rims" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at front:696,543 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Barnacle patch - lower right of the coil centre" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at front:399,267 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Open barnacle apertures" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at back:297,399 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Barnacle patch - mid flank rib band" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at iso2:295,96 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Ribbed limpet caps on the far shoulder" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at left:327,574 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "Barnacle spat band in the rib groove" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at front:456,508 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "barnacle cluster left of coil centre" --replace 2>&1 | head -1
python3 "$HERE/scripts/mc_select.py" --session "$SESSION" \
    --at front:484,547 --tolerance "$TOLERANCE" --threshold "$THRESHOLD" \
    --quiet --name "barnacle cluster below coil centre" --replace 2>&1 | head -1
