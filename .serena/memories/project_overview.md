# Code Canvas Plugin - Project Overview

## Purpose
A Svelte 5 canvas plugin with an event-sourced data model for managing architecture diagrams. Views are tabs in the canvas UI. The project enables composable visual hints and rendering control.

## Tech Stack
- **Frontend**: Svelte 5, TypeScript
- **Backend**: Node.js (vanilla HTTP server)
- **Testing**: Vitest
- **Event Model**: Event sourcing (JSONL-based)

## Project Structure
- `/client` - Svelte 5 frontend
  - `src/lib/events.js` - EventStore class for replaying events
  - `src/lib/events.test.js` - Tests for EventStore
  - `src/lib/state.svelte.js` - Reactive state
  - `src/lib/layout.js`, `drag.js`, `theme.js`, `config.js` - Utilities
- `/server` - Node.js HTTP server
  - `index.js` - Event persistence, API endpoints, static serving
- `.code-canvas/` - Runtime directory for events.jsonl and layouts

## Key Concepts
- **Event-sourced state**: All state computed from JSONL events, never mutated directly
- **Views**: Tabs with diagram data (tabNodes, tabConnections, filter)
- **Rendering hints**: New field to store composable visual hints (nodeShape, layout, etc.)

## Testing
```bash
npx vitest run client/src/lib/events.test.js --reporter=verbose
```

## Important Files for Task
- `client/src/lib/events.js` - Line 139-149 (view.created handler)
- `server/index.js` - Line 82 (view.created replay)
- `client/src/lib/events.test.js` - Add three new tests
