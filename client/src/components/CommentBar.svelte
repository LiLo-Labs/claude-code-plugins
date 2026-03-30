<script>
  /**
   * Comment bar — simple single-row comments at the bottom.
   */
  let { comments = [], onresolve, ondelete, onnavigate } = $props();

  let expanded = $state(true);
  const unresolved = $derived(comments.filter(c => !c.resolved));
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="cbar" class:collapsed={!expanded}>
  <div class="cbar-hdr" onclick={() => expanded = !expanded}>
    <h3>Comments</h3>
    <span class="badge">{unresolved.length}</span>
    <span class="tog">{expanded ? '\u25BC' : '\u25B2'}</span>
  </div>

  {#if expanded}
    <div class="cbar-body">
      {#each unresolved as comment}
        <div class="row">
          <span class="dot" class:user={comment.actor === 'user'} class:claude={comment.actor === 'claude'}></span>
          <span class="tgt" onclick={() => onnavigate?.(comment.target)}>{comment.targetLabel}</span>
          <span class="txt">{comment.text}</span>
          <button class="res" onclick={() => onresolve?.(comment.id)}>&#10003;</button>
          <button class="del" onclick={() => ondelete?.(comment.id)}>&times;</button>
        </div>
      {/each}
      {#if unresolved.length === 0}
        <span class="empty">No open comments</span>
      {/if}
    </div>
  {/if}
</div>

<style>
  .cbar { background: var(--gl); backdrop-filter: blur(16px); border-top: 1px solid var(--gl-b); max-height: 140px; overflow-y: auto; flex-shrink: 0; }
  .cbar.collapsed { max-height: 30px; overflow: hidden; }
  .cbar-hdr { display: flex; align-items: center; padding: 5px 14px; cursor: pointer; gap: 6px; }
  .cbar-hdr h3 { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: var(--tx-d); margin: 0; }
  .badge { font-size: 10px; background: var(--ac); color: white; padding: 0 5px; border-radius: 7px; font-weight: 600; }
  .tog { margin-left: auto; font-size: 10px; color: var(--tx-d); }
  .cbar-body { padding: 0 14px 6px; }
  .row { display: flex; align-items: center; gap: 6px; padding: 3px 0; border-bottom: 1px solid var(--bdr); font-size: 12px; }
  .row:last-child { border-bottom: none; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--tx-d); flex-shrink: 0; }
  .dot.user { background: var(--gr); }
  .dot.claude { background: var(--pu); }
  .tgt { color: var(--ac); font-weight: 600; white-space: nowrap; cursor: pointer; }
  .tgt:hover { text-decoration: underline; }
  .txt { color: var(--tx-m); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .res, .del { background: none; border: none; font-size: 13px; padding: 0 2px; cursor: pointer; }
  .res { color: var(--gr); }
  .del { color: var(--tx-d); }
  .del:hover { color: var(--rd); }
  .empty { font-size: 11px; color: var(--tx-d); }
</style>
