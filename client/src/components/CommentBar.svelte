<script>
  /**
   * Comment bar — expandable panel showing unresolved comments.
   * Each comment has target node, text, actor, resolve/delete actions.
   */
  let { comments = [], onresolve, ondelete, onnavigate } = $props();

  let expanded = $state(true);
  const unresolved = $derived(comments.filter(c => !c.resolved));
  const resolved = $derived(comments.filter(c => c.resolved));
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="cbar" class:collapsed={!expanded}>
  <div class="cbar-header" onclick={() => expanded = !expanded}>
    <h3>Comments</h3>
    <span class="badge">{unresolved.length}</span>
    <span class="toggle">{expanded ? '\u25BC' : '\u25B2'}</span>
  </div>

  {#if expanded}
    <div class="cbar-body">
      {#if unresolved.length === 0}
        <p class="empty">No open comments</p>
      {/if}

      {#each unresolved as comment}
        <div class="comment-row">
          <span class="actor" class:user={comment.actor === 'user'} class:claude={comment.actor === 'claude'}>
            {comment.actor}
          </span>
          <span class="target" onclick={() => onnavigate?.(comment.target)}>
            {comment.targetLabel}:
          </span>
          <span class="text">{comment.text}</span>
          <span class="actions">
            <button class="resolve" title="Resolve" onclick={() => onresolve?.(comment.id)}>&#10003;</button>
            <button class="delete" title="Delete" onclick={() => ondelete?.(comment.id)}>&times;</button>
          </span>
        </div>
      {/each}

      {#if resolved.length > 0}
        <div class="resolved-header">Resolved ({resolved.length})</div>
        {#each resolved as comment}
          <div class="comment-row resolved">
            <span class="actor">{comment.actor}</span>
            <span class="target">{comment.targetLabel}:</span>
            <span class="text">{comment.text}</span>
          </div>
        {/each}
      {/if}
    </div>
  {/if}
</div>

<style>
  .cbar {
    background: var(--gl); backdrop-filter: blur(16px);
    border-top: 1px solid var(--gl-b);
    max-height: 180px; overflow-y: auto; flex-shrink: 0;
    transition: max-height 0.2s;
  }
  .cbar.collapsed { max-height: 32px; overflow: hidden; }
  .cbar-header {
    display: flex; align-items: center; padding: 6px 14px;
    cursor: pointer; gap: 6px;
  }
  .cbar-header h3 {
    font-size: 10px; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--tx-d); margin: 0;
  }
  .badge {
    font-size: 10px; background: var(--ac); color: white;
    padding: 0 5px; border-radius: 7px; font-weight: 600;
  }
  .toggle { margin-left: auto; font-size: 10px; color: var(--tx-d); }

  .cbar-body { padding: 0 14px 8px; }
  .empty { font-size: 11px; color: var(--tx-d); text-align: center; padding: 4px 0; }

  .comment-row {
    display: flex; align-items: start; gap: 6px;
    padding: 5px 0; border-bottom: 1px solid var(--bdr);
    font-size: 12px;
  }
  .comment-row:last-child { border-bottom: none; }
  .comment-row.resolved { opacity: 0.4; }

  .actor {
    font-size: 10px; padding: 1px 5px; border-radius: 3px;
    font-weight: 600; flex-shrink: 0;
  }
  .actor.user { background: rgba(16,185,129,.15); color: var(--gr); }
  .actor.claude { background: rgba(168,85,247,.15); color: var(--pu); }

  .target {
    color: var(--ac); font-weight: 600; white-space: nowrap;
    cursor: pointer;
  }
  .target:hover { text-decoration: underline; }
  .text { color: var(--tx-m); flex: 1; }

  .actions { display: flex; gap: 2px; flex-shrink: 0; }
  .actions button {
    background: none; border: none; font-size: 14px;
    padding: 0 3px; cursor: pointer;
  }
  .resolve { color: var(--gr); }
  .resolve:hover { color: #34d399; }
  .delete { color: var(--tx-d); }
  .delete:hover { color: var(--rd); }

  .resolved-header {
    font-size: 10px; color: var(--tx-d); text-transform: uppercase;
    letter-spacing: 0.06em; padding: 8px 0 4px;
    border-top: 1px solid var(--bdr); margin-top: 4px;
  }
</style>
