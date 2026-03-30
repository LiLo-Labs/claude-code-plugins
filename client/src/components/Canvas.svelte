<script>
  import { appState } from '../lib/state.svelte.js';

  let svgEl = $state(null);
  let wrapEl = $state(null);
  let isPanning = $state(false);
  let panStart = { x: 0, y: 0, ox: 0, oy: 0 };

  function handleWheel(e) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.06 : 0.06;
    appState.zoom = Math.max(0.15, Math.min(3, appState.zoom + delta));
  }

  function handleMouseDown(e) {
    // Only pan when clicking directly on svg or background
    if (e.target !== svgEl && !e.target.classList.contains('canvas-bg-rect')) return;
    isPanning = true;
    panStart = { x: e.clientX, y: e.clientY, ox: appState.panX, oy: appState.panY };
    // Deselect all
    appState.selectedIds = new Set();
  }

  function handleMouseMove(e) {
    if (!isPanning) return;
    appState.panX = panStart.ox + (e.clientX - panStart.x);
    appState.panY = panStart.oy + (e.clientY - panStart.y);
  }

  function handleMouseUp() {
    isPanning = false;
  }

  function getViewBox() {
    if (!wrapEl) return '0 0 1200 800';
    const rect = wrapEl.getBoundingClientRect();
    const vbX = -appState.panX / appState.zoom;
    const vbY = -appState.panY / appState.zoom;
    const vbW = rect.width / appState.zoom;
    const vbH = rect.height / appState.zoom;
    return `${vbX} ${vbY} ${vbW} ${vbH}`;
  }

  // Expose svgEl for coordinate transforms in drag system
  let { children } = $props();
  export function getSvgEl() { return svgEl; }
</script>

<svelte:window onmousemove={handleMouseMove} onmouseup={handleMouseUp} />

<div class="canvas-wrap" bind:this={wrapEl}>
  <svg
    bind:this={svgEl}
    class="canvas-svg"
    class:panning={isPanning}
    viewBox={getViewBox()}
    xmlns="http://www.w3.org/2000/svg"
    onwheel={handleWheel}
    onmousedown={handleMouseDown}
  >
    <!-- Background grid rendered in SVG for proper pan/zoom -->
    <defs>
      <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
        <circle cx="1" cy="1" r="0.8" fill="var(--gd)" />
      </pattern>
    </defs>
    <rect class="canvas-bg-rect" x="-5000" y="-5000" width="10000" height="10000" fill="url(#grid)" />

    {@render children()}
  </svg>
</div>

<style>
  .canvas-wrap {
    flex: 1;
    position: relative;
    overflow: hidden;
    background: var(--bg);
  }
  .canvas-svg {
    width: 100%;
    height: 100%;
    cursor: grab;
  }
  .canvas-svg.panning {
    cursor: grabbing;
  }
</style>
