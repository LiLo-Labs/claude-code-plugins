# UX Gap Analysis v2 (2026-03-30)

From UX agent comparing current implementation vs design spec + study-tutor reference.

## Critical

### G1. Node fill — uniform dark vs semantic per-node color
Nodes all look identical (#1a1d2e). Reference uses distinct colors per subsystem (green for widgets, purple for orchestration, etc.). Fix: use `node.color` or `depthTint(node.depth, 0.35)` as fill.

### G2. Node dimensions — 260x60 vs spec 280x90
Way too cramped. Title + subtitle + badges don't fit. Fix: GRID nodeW=280, nodeH=90.

## High

### G3. Subtitle always visible — spec says hide, show on hover
60px nodes can't fit subtitle. Remove from node, show in tooltip/panel only.

### G4. Text color not derived from depth
All text is white. Reference uses depth-tinted text (green text on green nodes). Add DEPTH_TEXT_COLORS to config.

### G5. Edge label pill — missing border, wrong size
No stroke on pill, 24px tall (spec: 20px), rx=6 (spec: rx=10). Fix: add 1px border, 20px height, rx=10, 11px font.

### G6. Two competing tab controls
Topbar has Canvas/Timeline/Diff/Story AND ViewTabs has All/Custom. Confusing. Consolidate into one tab bar.

### G9. Status badges completely absent
Only a checkmark for "done". No pills for "in-progress", "planned". No comment count number. Confidence dots too small (2.5px, need 4px).

## Medium

### G7. Arrow markers slightly oversized (12x8 vs spec 10x7)
Also needs ID normalization (lowercase hex).

### G8. Dot grid too sparse and sub-pixel
0.8px radius dots at 28px spacing barely visible. Fix: 1.2px radius, 24px grid, 0.4 opacity.

### G10. Left depth color band missing
Spec calls for 5px left bar in depth color. Not rendered.

## Low

### G11. Selection outline acceptable as-is
### G12. Project name hardcoded "Code Canvas"
