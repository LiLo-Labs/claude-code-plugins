#!/bin/bash
# Seed a project with demo data for testing the canvas
# Usage: ./scripts/seed-demo.sh [project-dir]

PROJECT_DIR="${1:-/tmp/canvas-demo}"
CANVAS_DIR="$PROJECT_DIR/.code-canvas"
EVENTS_FILE="$CANVAS_DIR/events.jsonl"

mkdir -p "$CANVAS_DIR/layouts"
> "$EVENTS_FILE"

post() { echo "$1" >> "$EVENTS_FILE"; }

# Nodes
post '{"id":"ev_01","ts":"2026-03-29T10:00:00Z","type":"node.created","actor":"claude","data":{"nodeId":"root","label":"Code Canvas Plugin","subtitle":"Design knowledge graph + visual interface","parent":null,"depth":"system","category":"arch","confidence":2}}'
post '{"id":"ev_02","ts":"2026-03-29T10:00:01Z","type":"node.created","actor":"claude","data":{"nodeId":"data","label":"Data Model","subtitle":"Event store, graph engine, views","parent":"root","depth":"domain","category":"arch","confidence":2}}'
post '{"id":"ev_03","ts":"2026-03-29T10:00:02Z","type":"node.created","actor":"claude","data":{"nodeId":"events","label":"Event Store","subtitle":"JSONL append-only log","parent":"data","depth":"module","category":"arch","confidence":3}}'
post '{"id":"ev_04","ts":"2026-03-29T10:00:03Z","type":"node.created","actor":"claude","data":{"nodeId":"graph-e","label":"Graph Engine","subtitle":"In-memory from event replay","parent":"data","depth":"module","category":"arch","confidence":1}}'
post '{"id":"ev_05","ts":"2026-03-29T10:00:04Z","type":"node.created","actor":"claude","data":{"nodeId":"node-m","label":"Node Model","subtitle":"Core node schema","parent":"data","depth":"module","category":"arch","confidence":3}}'
post '{"id":"ev_06","ts":"2026-03-29T10:00:05Z","type":"node.created","actor":"claude","data":{"nodeId":"ui","label":"Canvas UI","subtitle":"Svelte + SVG components","parent":"root","depth":"domain","category":"arch","confidence":3}}'
post '{"id":"ev_07","ts":"2026-03-29T10:00:06Z","type":"node.created","actor":"claude","data":{"nodeId":"nodes-r","label":"Node Renderer","subtitle":"Drag, expand, containment","parent":"ui","depth":"module","category":"arch","confidence":3}}'
post '{"id":"ev_08","ts":"2026-03-29T10:00:07Z","type":"node.created","actor":"claude","data":{"nodeId":"edges-r","label":"Edge Renderer","subtitle":"Bezier + ports + edit","parent":"ui","depth":"module","category":"flow","confidence":2}}'
post '{"id":"ev_09","ts":"2026-03-29T10:00:08Z","type":"node.created","actor":"claude","data":{"nodeId":"layout-e","label":"Layout Engine","subtitle":"Auto layout + persistence","parent":"ui","depth":"module","category":"arch","confidence":0}}'
post '{"id":"ev_10","ts":"2026-03-29T10:00:09Z","type":"node.created","actor":"claude","data":{"nodeId":"server","label":"Server","subtitle":"Static + API, multi-instance","parent":"root","depth":"domain","category":"arch","confidence":3}}'
post '{"id":"ev_11","ts":"2026-03-29T10:00:10Z","type":"node.created","actor":"claude","data":{"nodeId":"integ","label":"Integration","subtitle":"Hooks + context + plugin API","parent":"root","depth":"domain","category":"flow","confidence":2}}'
post '{"id":"ev_12","ts":"2026-03-29T10:00:11Z","type":"node.created","actor":"claude","data":{"nodeId":"hooks","label":"Hook System","subtitle":"6 lifecycle hooks","parent":"integ","depth":"module","category":"arch","confidence":2}}'
post '{"id":"ev_13","ts":"2026-03-29T10:00:12Z","type":"node.created","actor":"claude","data":{"nodeId":"ctx-lvl","label":"Context Levels","subtitle":"L0-L3 adaptive for Claude","parent":"integ","depth":"module","category":"flow","confidence":2}}'

# Statuses
post '{"id":"ev_20","ts":"2026-03-29T11:00:00Z","type":"node.status","actor":"user","data":{"nodeId":"root","status":"in-progress","prev":"planned"}}'
post '{"id":"ev_21","ts":"2026-03-29T11:00:01Z","type":"node.status","actor":"user","data":{"nodeId":"ui","status":"in-progress","prev":"planned"}}'
post '{"id":"ev_22","ts":"2026-03-29T11:00:02Z","type":"node.status","actor":"user","data":{"nodeId":"nodes-r","status":"in-progress","prev":"planned"}}'
post '{"id":"ev_23","ts":"2026-03-29T11:00:03Z","type":"node.status","actor":"claude","data":{"nodeId":"server","status":"done","prev":"planned"}}'
post '{"id":"ev_24","ts":"2026-03-29T11:00:04Z","type":"node.status","actor":"claude","data":{"nodeId":"node-m","status":"done","prev":"planned"}}'

# Edges
post '{"id":"ev_30","ts":"2026-03-29T10:30:00Z","type":"edge.created","actor":"claude","data":{"edgeId":"e1","from":"events","to":"graph-e","label":"replay","edgeType":"data-flow","color":"#3b82f6"}}'
post '{"id":"ev_31","ts":"2026-03-29T10:30:01Z","type":"edge.created","actor":"claude","data":{"edgeId":"e2","from":"graph-e","to":"ui","label":"state","edgeType":"data-flow","color":"#14b8a6"}}'
post '{"id":"ev_32","ts":"2026-03-29T10:30:02Z","type":"edge.created","actor":"claude","data":{"edgeId":"e3","from":"hooks","to":"ctx-lvl","label":"trigger","edgeType":"dependency","color":"#f97316"}}'
post '{"id":"ev_33","ts":"2026-03-29T10:30:03Z","type":"edge.created","actor":"claude","data":{"edgeId":"e4","from":"server","to":"events","label":"r/w","edgeType":"dependency","color":"#64748b"}}'

# Decisions
post '{"id":"ev_40","ts":"2026-03-29T12:00:00Z","type":"decision.recorded","actor":"user","data":{"nodeId":"root","type":"decision","chosen":"JSONL event store","alternatives":["SQLite","Gun.js","LevelGraph"],"reason":"Portable, git-friendly, easy migration path"}}'
post '{"id":"ev_41","ts":"2026-03-29T12:00:01Z","type":"decision.recorded","actor":"user","data":{"nodeId":"ui","type":"decision","chosen":"Svelte + SVG","alternatives":["React + Canvas","Vanilla JS","WebGL"],"reason":"Lightweight, debuggable, component model"}}'

# Comments
post '{"id":"ev_50","ts":"2026-03-29T13:00:00Z","type":"comment.added","actor":"user","data":{"commentId":"c1","target":"layout-e","targetLabel":"Layout Engine","text":"Should we support saved layout presets per view?","actor":"user"}}'
post '{"id":"ev_51","ts":"2026-03-29T13:00:01Z","type":"comment.added","actor":"claude","data":{"commentId":"c2","target":"hooks","targetLabel":"Hook System","text":"FileChanged hook needs to only fire for .code-canvas/ files","actor":"claude"}}'

echo "Seeded $EVENTS_FILE with $(wc -l < "$EVENTS_FILE" | tr -d ' ') events"
