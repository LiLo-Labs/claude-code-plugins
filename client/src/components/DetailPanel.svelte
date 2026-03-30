<script>
  /**
   * DetailPanel — right sidebar showing properties, decisions, breadcrumbs for selected node.
   */
  import { getAncestors } from '../lib/layout.js';

  let { node = null, nodes, store, onselect, onclose } = $props();

  const STATUS_COLORS = { done: '#10b981', 'in-progress': '#eab308', planned: '#3b82f6', placeholder: '#64748b' };

  const ancestors = $derived(node ? getAncestors(node.id, nodes) : []);
  const decisions = $derived(node ? store.getNodeDecisions(node.id) : []);
</script>

<div class="panel">
  <div class="hdr">
    <span class="title">{node?.label || 'Details'}</span>
    <button class="close" onclick={onclose}>&times;</button>
  </div>

  <div class="body">
    {#if node}
      <!-- Breadcrumb -->
      {#if ancestors.length > 0}
        <div class="breadcrumb">
          {#each ancestors as anc}
            <span class="bc-item" onclick={() => onselect?.(anc.id)}>
              {anc.label}
            </span>
            <span class="bc-sep">&#8250;</span>
          {/each}
          <span class="bc-current">{node.label}</span>
        </div>
      {/if}

      <div class="section">
        <div class="sec-title">Properties</div>
        <div class="field"><span class="fl">Type</span><span class="fv">{node.depth}</span></div>
        <div class="field"><span class="fl">Category</span><span class="fv">{node.category}</span></div>
        <div class="field">
          <span class="fl">Status</span>
          <span class="fv" style="color: {STATUS_COLORS[node.status]}">{node.status}</span>
        </div>
        <div class="field"><span class="fl">Completeness</span><span class="fv">{Math.round(node.completeness * 100)}%</span></div>
        <div class="conf-row">
          <span class="fl">Confidence:</span>
          {#each [0, 1, 2] as i}
            <span class="conf-dot" class:filled={i < node.confidence}></span>
          {/each}
        </div>
      </div>

      <div class="section">
        <div class="sec-title">Description</div>
        <p class="desc">{node.subtitle}</p>
      </div>

      {#if decisions.length > 0}
        <div class="section">
          <div class="sec-title">Decisions</div>
          {#each decisions as dec}
            <div class="dec-card" class:wk={dec.type === 'workaround'}>
              <div class="dec-chosen" class:dec-wk={dec.type === 'workaround'}>
                {dec.type === 'workaround' ? '\u26A0' : '\u2713'} {dec.chosen}
              </div>
              <div class="dec-alts">
                {dec.type === 'workaround' ? 'Originally' : 'Alternatives'}: {dec.alternatives.join(', ')}
              </div>
              <div class="dec-reason">"{dec.reason}"</div>
            </div>
          {/each}
        </div>
      {/if}
    {:else}
      <p class="empty">Select a node to view details</p>
    {/if}
  </div>
</div>

<style>
  .panel { display: flex; flex-direction: column; height: 100%; }
  .hdr { padding: 12px 14px; border-bottom: 1px solid var(--bdr); display: flex; align-items: center; justify-content: space-between; }
  .title { font-size: 14px; font-weight: 600; }
  .close { border: none; background: transparent; color: var(--tx-d); font-size: 14px; cursor: pointer; border-radius: 3px; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; }
  .close:hover { background: var(--bg-e); color: var(--tx); }
  .body { flex: 1; padding: 14px; overflow-y: auto; }
  .body::-webkit-scrollbar { width: 4px; }
  .body::-webkit-scrollbar-thumb { background: var(--bdr); border-radius: 2px; }

  .breadcrumb { display: flex; flex-wrap: wrap; gap: 3px; margin-bottom: 10px; font-size: 11px; }
  .bc-item { color: var(--tx-d); cursor: pointer; padding: 2px 5px; border-radius: 3px; }
  .bc-item:hover { background: var(--bg-e); color: var(--tx); }
  .bc-sep { color: var(--tx-d); padding: 0 2px; }
  .bc-current { color: var(--ac); font-weight: 600; padding: 2px 5px; }

  .section { margin-bottom: 14px; }
  .sec-title { font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--tx-d); margin-bottom: 5px; }
  .field { display: flex; justify-content: space-between; padding: 3px 0; font-size: 12px; }
  .fl { color: var(--tx-m); }
  .fv { color: var(--tx); }
  .desc { font-size: 12px; color: var(--tx-m); }
  .conf-row { display: flex; align-items: center; gap: 4px; margin-top: 4px; font-size: 12px; }
  .conf-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--bdr); }
  .conf-dot.filled { background: var(--ac); }

  .dec-card { background: var(--bg); border: 1px solid var(--bdr); border-radius: 6px; padding: 10px; margin-bottom: 8px; }
  .dec-card.wk { border-color: var(--or); }
  .dec-chosen { font-size: 12px; font-weight: 600; color: var(--gr); margin-bottom: 3px; }
  .dec-chosen.dec-wk { color: var(--or); }
  .dec-alts { font-size: 11px; color: var(--tx-d); margin-bottom: 3px; }
  .dec-reason { font-size: 11px; color: var(--tx-m); font-style: italic; }

  .empty { font-size: 12px; color: var(--tx-d); text-align: center; padding: 20px 0; }
</style>
