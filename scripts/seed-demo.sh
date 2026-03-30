#!/bin/bash
# Seed demo data — per-tab authored diagrams (study-tutor model)
PROJECT_DIR="${1:-/tmp/canvas-demo}"
CANVAS_DIR="$PROJECT_DIR/.code-canvas"
EVENTS_FILE="$CANVAS_DIR/events.jsonl"
mkdir -p "$CANVAS_DIR/layouts"
> "$EVENTS_FILE"
post() { echo "$1" >> "$EVENTS_FILE"; }

# ── Node Registry (canonical definitions) ──
post '{"id":"ev_01","ts":"2026-03-29T10:00:00Z","type":"node.created","actor":"claude","data":{"nodeId":"root","label":"Code Canvas Plugin","subtitle":"Design knowledge graph","parent":null,"depth":"system","category":"arch","confidence":2}}'
post '{"id":"ev_02","ts":"2026-03-29T10:00:01Z","type":"node.created","actor":"claude","data":{"nodeId":"data","label":"Data Model","subtitle":"Event store + graph engine","parent":"root","depth":"domain","category":"arch","confidence":2}}'
post '{"id":"ev_03","ts":"2026-03-29T10:00:02Z","type":"node.created","actor":"claude","data":{"nodeId":"events","label":"Event Store","subtitle":"Append-only JSONL log","parent":"data","depth":"module","category":"arch","confidence":3}}'
post '{"id":"ev_04","ts":"2026-03-29T10:00:03Z","type":"node.created","actor":"claude","data":{"nodeId":"graph-e","label":"Graph Engine","subtitle":"In-memory from replay","parent":"data","depth":"module","category":"arch","confidence":1}}'
post '{"id":"ev_05","ts":"2026-03-29T10:00:04Z","type":"node.created","actor":"claude","data":{"nodeId":"ui","label":"Canvas UI","subtitle":"Svelte + SVG components","parent":"root","depth":"domain","category":"arch","confidence":3}}'
post '{"id":"ev_06","ts":"2026-03-29T10:00:05Z","type":"node.created","actor":"claude","data":{"nodeId":"nodes-r","label":"Node Renderer","subtitle":"Cards, drag, visual style","parent":"ui","depth":"module","category":"arch","confidence":3}}'
post '{"id":"ev_07","ts":"2026-03-29T10:00:06Z","type":"node.created","actor":"claude","data":{"nodeId":"edges-r","label":"Edge Renderer","subtitle":"Bezier + labels + arrows","parent":"ui","depth":"module","category":"flow","confidence":2}}'
post '{"id":"ev_08","ts":"2026-03-29T10:00:07Z","type":"node.created","actor":"claude","data":{"nodeId":"layout-e","label":"Layout Engine","subtitle":"Grid-based + persistence","parent":"ui","depth":"module","category":"arch","confidence":0}}'
post '{"id":"ev_09","ts":"2026-03-29T10:00:08Z","type":"node.created","actor":"claude","data":{"nodeId":"server","label":"Server","subtitle":"Static + API, multi-instance","parent":"root","depth":"domain","category":"arch","confidence":3}}'
post '{"id":"ev_10","ts":"2026-03-29T10:00:09Z","type":"node.created","actor":"claude","data":{"nodeId":"integ","label":"Integration","subtitle":"Hooks + context + plugins","parent":"root","depth":"domain","category":"flow","confidence":2}}'
post '{"id":"ev_11","ts":"2026-03-29T10:00:10Z","type":"node.created","actor":"claude","data":{"nodeId":"hooks","label":"Hook System","subtitle":"6 lifecycle hooks","parent":"integ","depth":"module","category":"arch","confidence":2}}'
post '{"id":"ev_12","ts":"2026-03-29T10:00:11Z","type":"node.created","actor":"claude","data":{"nodeId":"ctx-lvl","label":"Context Levels","subtitle":"L0-L3 adaptive for Claude","parent":"integ","depth":"module","category":"flow","confidence":2}}'
post '{"id":"ev_13","ts":"2026-03-29T10:00:12Z","type":"node.created","actor":"claude","data":{"nodeId":"views","label":"View System","subtitle":"Tabs, Timeline, Diff, Story","parent":"root","depth":"module","category":"arch","confidence":1}}'

# Statuses
post '{"id":"ev_20","ts":"2026-03-29T11:00:00Z","type":"node.status","actor":"user","data":{"nodeId":"root","status":"in-progress","prev":"planned"}}'
post '{"id":"ev_21","ts":"2026-03-29T11:00:01Z","type":"node.status","actor":"user","data":{"nodeId":"ui","status":"in-progress","prev":"planned"}}'
post '{"id":"ev_22","ts":"2026-03-29T11:00:02Z","type":"node.status","actor":"user","data":{"nodeId":"nodes-r","status":"in-progress","prev":"planned"}}'
post '{"id":"ev_23","ts":"2026-03-29T11:00:03Z","type":"node.status","actor":"claude","data":{"nodeId":"server","status":"done","prev":"planned"}}'
post '{"id":"ev_24","ts":"2026-03-29T11:00:04Z","type":"node.status","actor":"claude","data":{"nodeId":"events","status":"done","prev":"planned"}}'

# Decisions
post '{"id":"ev_40","ts":"2026-03-29T12:00:00Z","type":"decision.recorded","actor":"user","data":{"nodeId":"root","type":"decision","chosen":"JSONL event store","alternatives":["SQLite","Gun.js"],"reason":"Portable, git-friendly"}}'
post '{"id":"ev_41","ts":"2026-03-29T12:00:01Z","type":"decision.recorded","actor":"user","data":{"nodeId":"ui","type":"decision","chosen":"Svelte + SVG","alternatives":["React","Vanilla JS"],"reason":"Lightweight, debuggable"}}'

# Comments
post '{"id":"ev_50","ts":"2026-03-29T13:00:00Z","type":"comment.added","actor":"user","data":{"commentId":"c1","target":"layout-e","targetLabel":"Layout Engine","text":"Grid-based from row/col — proven approach","actor":"user"}}'
post '{"id":"ev_51","ts":"2026-03-29T13:00:01Z","type":"comment.added","actor":"claude","data":{"commentId":"c2","target":"hooks","targetLabel":"Hook System","text":"FileChanged hook needs filtering","actor":"claude"}}'

# ── Tab 1: System Overview ──
post '{"id":"ev_60","ts":"2026-03-29T14:00:00Z","type":"view.created","actor":"claude","data":{"viewId":"overview","name":"System Overview","story":"High-level architecture — event-sourced design knowledge graph","tabNodes":[{"nodeId":"root","row":0,"col":1,"cols":3,"color":"#1e293b","textColor":"#94a3b8"},{"nodeId":"data","row":1,"col":0,"cols":3,"color":"#1a2a3c","textColor":"#7ab8f5"},{"nodeId":"ui","row":1,"col":1,"cols":3,"color":"#1a3a2c","textColor":"#6af59a"},{"nodeId":"server","row":1,"col":2,"cols":3,"color":"#2a1a3a","textColor":"#c9a8f5"},{"nodeId":"integ","row":2,"col":0,"cols":3,"color":"#3a2a1c","textColor":"#f5c87a"},{"nodeId":"views","row":2,"col":1,"cols":3,"color":"#1a1a2a","textColor":"#94a3b8"},{"nodeId":"events","row":2,"col":2,"cols":3,"color":"#1a1a2a","textColor":"#94a3b8"}],"tabConnections":[{"from":"root","to":"data","color":"#475569","label":""},{"from":"root","to":"ui","color":"#475569","label":""},{"from":"root","to":"server","color":"#475569","label":""},{"from":"data","to":"events","color":"#3b82f6","label":"persists"},{"from":"events","to":"ui","color":"#14b8a6","label":"state"},{"from":"server","to":"events","color":"#64748b","label":"r/w"},{"from":"integ","to":"ui","color":"#f97316","label":"hooks"},{"from":"integ","to":"events","color":"#f97316","label":"context"}]}}'

# ── Tab 2: Data Layer ──
post '{"id":"ev_61","ts":"2026-03-29T14:00:01Z","type":"view.created","actor":"claude","data":{"viewId":"data-layer","name":"Data Layer","story":"Event-sourced persistence — JSONL log with in-memory graph replay","tabNodes":[{"nodeId":"data","row":0,"col":1,"cols":3,"color":"#1a2a3c","textColor":"#7ab8f5"},{"nodeId":"events","row":1,"col":0,"cols":3,"color":"#1a1a2a","textColor":"#94a3b8"},{"nodeId":"graph-e","row":1,"col":2,"cols":3,"color":"#1a1a2a","textColor":"#94a3b8"},{"nodeId":"server","row":2,"col":0,"cols":3,"color":"#2a1a3a","textColor":"#c9a8f5"},{"nodeId":"ctx-lvl","row":2,"col":2,"cols":3,"color":"#3a2a1c","textColor":"#f5c87a"}],"tabConnections":[{"from":"data","to":"events","color":"#3b82f6","label":"writes"},{"from":"data","to":"graph-e","color":"#3b82f6","label":"reads"},{"from":"events","to":"graph-e","color":"#8b5cf6","label":"replay"},{"from":"server","to":"events","color":"#64748b","label":"r/w"},{"from":"graph-e","to":"ctx-lvl","color":"#f59e0b","label":"state"}]}}'

# ── Tab 3: UI Components ──
post '{"id":"ev_62","ts":"2026-03-29T14:00:02Z","type":"view.created","actor":"claude","data":{"viewId":"ui-layer","name":"UI Components","story":"Svelte + SVG canvas rendering pipeline","tabNodes":[{"nodeId":"ui","row":0,"col":1,"cols":3,"color":"#1a3a2c","textColor":"#6af59a"},{"nodeId":"nodes-r","row":1,"col":0,"cols":3,"color":"#2a4a3c","textColor":"#8fd"},{"nodeId":"edges-r","row":1,"col":1,"cols":3,"color":"#2a3a4c","textColor":"#9bf"},{"nodeId":"layout-e","row":1,"col":2,"cols":3,"color":"#3a2a4c","textColor":"#c9a8f5"},{"nodeId":"views","row":2,"col":1,"cols":3,"color":"#1e293b","textColor":"#94a3b8"}],"tabConnections":[{"from":"ui","to":"nodes-r","color":"#10b981","label":"renders"},{"from":"ui","to":"edges-r","color":"#10b981","label":"renders"},{"from":"layout-e","to":"ui","color":"#8b5cf6","label":"positions"},{"from":"views","to":"ui","color":"#64748b","label":"tab data"}]}}'

# ── Tab 4: Integration ──
post '{"id":"ev_63","ts":"2026-03-29T14:00:03Z","type":"view.created","actor":"claude","data":{"viewId":"integration","name":"Integration","story":"How the canvas stays connected to Claude Code and other plugins","tabNodes":[{"nodeId":"integ","row":0,"col":1,"cols":3,"color":"#3a2a1c","textColor":"#f5c87a"},{"nodeId":"hooks","row":1,"col":0,"cols":3,"color":"#3a2a4c","textColor":"#c9a8f5"},{"nodeId":"ctx-lvl","row":1,"col":2,"cols":3,"color":"#2a1a3a","textColor":"#c9a8f5"},{"nodeId":"events","row":2,"col":1,"cols":3,"color":"#1a1a2a","textColor":"#94a3b8"}],"tabConnections":[{"from":"integ","to":"hooks","color":"#f97316","label":"lifecycle"},{"from":"integ","to":"ctx-lvl","color":"#f97316","label":"context API"},{"from":"hooks","to":"events","color":"#8b5cf6","label":"emit events"},{"from":"ctx-lvl","to":"events","color":"#8b5cf6","label":"read state"}]}}'

echo "Seeded $EVENTS_FILE with $(wc -l < "$EVENTS_FILE" | tr -d ' ') events"
