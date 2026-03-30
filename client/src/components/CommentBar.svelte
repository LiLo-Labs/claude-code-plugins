<script>
  /**
   * Comment bar — expandable panel showing comments with full context.
   * Each comment shows: actor badge, target node, text, timestamp, actions.
   * Click target to navigate. Resolve/delete inline.
   */
  let { comments = [], nodes = new Map(), onresolve, ondelete, onnavigate } = $props();

  let expanded = $state(true);
  const unresolved = $derived(comments.filter(c => !c.resolved));
  const resolved = $derived(comments.filter(c => c.resolved));

  function formatTime(ts) {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      const now = new Date();
      const diff = now - d;
      if (diff < 60000) return 'just now';
      if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
      if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
      return d.toLocaleDateString();
    } catch { return ''; }
  }

  function getNodeSubtitle(targetId) {
    const node = nodes.get(targetId);
    return node?.subtitle || '';
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="cbar" class:collapsed={!expanded}>
  <div class="cbar-header" onclick={() => expanded = !expanded}>
    <h3>Comments</h3>
    {#if unresolved.length > 0}
      <span class="badge">{unresolved.length} open</span>
    {/if}
    {#if resolved.length > 0}
      <span class="badge resolved-badge">{resolved.length} resolved</span>
    {/if}
    <span class="toggle">{expanded ? '\u25BC' : '\u25B2'}</span>
  </div>

  {#if expanded}
    <div class="cbar-body">
      {#if unresolved.length === 0 && resolved.length === 0}
        <p class="empty">No comments yet — right-click a node to add one</p>
      {/if}

      {#each unresolved as comment}
        <div class="comment-card">
          <div class="comment-top">
            <span class="actor" class:user={comment.actor === 'user'} class:claude={comment.actor === 'claude'}>
              {comment.actor}
            </span>
            <span class="target" onclick={() => onnavigate?.(comment.target)}>
              {comment.targetLabel}
            </span>
            <span class="time">{formatTime(comment.ts)}</span>
            <span class="actions">
              <button class="resolve" title="Resolve" onclick={() => onresolve?.(comment.id)}>&#10003;</button>
              <button class="delete" title="Delete" onclick={() => ondelete?.(comment.id)}>&times;</button>
            </span>
          </div>
          <div class="comment-text">{comment.text}</div>
          {#if getNodeSubtitle(comment.target)}
            <div class="comment-context">on: {getNodeSubtitle(comment.target)}</div>
          {/if}
        </div>
      {/each}

      {#if resolved.length > 0}
        <div class="resolved-header">Resolved ({resolved.length})</div>
        {#each resolved as comment}
          <div class="comment-card faded">
            <div class="comment-top">
              <span class="actor">{comment.actor}</span>
              <span class="target">{comment.targetLabel}</span>
              {#if comment.resolvedBy}
                <span class="time">resolved by {comment.resolvedBy}</span>
              {/if}
            </div>
            <div class="comment-text">{comment.text}</div>
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
    max-height: 220px; overflow-y: auto; flex-shrink: 0;
    transition: max-height 0.2s;
  }
  .cbar.collapsed { max-height: 34px; overflow: hidden; }
  .cbar-header {
    display: flex; align-items: center; padding: 7px 14px;
    cursor: pointer; gap: 8px;
  }
  .cbar-header h3 {
    font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--tx-d); margin: 0;
  }
  .badge {
    font-size: 10px; background: var(--ac); color: white;
    padding: 1px 7px; border-radius: 8px; font-weight: 600;
  }
  .resolved-badge { background: var(--gr); }
  .toggle { margin-left: auto; font-size: 10px; color: var(--tx-d); }

  .cbar-body { padding: 0 14px 10px; }
  .empty { font-size: 11px; color: var(--tx-d); text-align: center; padding: 6px 0; }

  .comment-card {
    background: var(--bg); border: 1px solid var(--bdr);
    border-radius: 6px; padding: 8px 10px; margin-bottom: 6px;
  }
  .comment-card.faded { opacity: 0.4; }

  .comment-top {
    display: flex; align-items: center; gap: 6px;
    margin-bottom: 4px; font-size: 11px;
  }

  .actor {
    font-size: 10px; padding: 1px 6px; border-radius: 3px;
    font-weight: 600; flex-shrink: 0;
    background: var(--bg-e); color: var(--tx-d);
  }
  .actor.user { background: rgba(16,185,129,.15); color: var(--gr); }
  .actor.claude { background: rgba(168,85,247,.15); color: var(--pu); }

  .target {
    color: var(--ac); font-weight: 600; cursor: pointer;
    white-space: nowrap;
  }
  .target:hover { text-decoration: underline; }

  .time { color: var(--tx-d); font-size: 10px; margin-left: auto; }

  .comment-text { font-size: 12px; color: var(--tx); line-height: 1.4; }
  .comment-context { font-size: 10px; color: var(--tx-d); margin-top: 3px; font-style: italic; }

  .actions { display: flex; gap: 2px; flex-shrink: 0; }
  .actions button {
    background: none; border: none; font-size: 14px;
    padding: 0 4px; cursor: pointer;
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
