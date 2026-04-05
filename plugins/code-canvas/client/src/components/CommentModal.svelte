<script>
  let { visible = false, node = null, onsave, onclose } = $props();
  let text = $state('');

  function handleSave() {
    if (!text.trim() || !node) return;
    onsave?.(node.id, node.label, text.trim());
    text = '';
    onclose?.();
  }
</script>

{#if visible && node}
  <div class="overlay" onclick={onclose}>
    <div class="modal" onclick={(e) => e.stopPropagation()}>
      <h3>{node.label}</h3>
      <p class="sub">{node.subtitle}</p>
      <textarea bind:value={text} placeholder="What would you change about this component?" rows="3"></textarea>
      <div class="actions">
        <button class="cancel" onclick={onclose}>Cancel</button>
        <button class="save" onclick={handleSave}>Save Comment</button>
      </div>
    </div>
  </div>
{/if}

<svelte:window onkeydown={(e) => {
  if (e.key === 'Escape' && visible) onclose?.();
  if (e.key === 'Enter' && !e.shiftKey && visible) { e.preventDefault(); handleSave(); }
}} />

<style>
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex; align-items: center; justify-content: center; z-index: 200; }
  .modal { background: var(--bg-e); border: 1px solid var(--bdr); border-radius: 10px; padding: 20px; width: 400px; box-shadow: 0 12px 40px var(--sh); }
  h3 { font-size: 14px; color: var(--tx); margin-bottom: 4px; }
  .sub { font-size: 12px; color: var(--tx-d); margin-bottom: 12px; }
  textarea { width: 100%; background: var(--bg); border: 1px solid var(--bdr); border-radius: 6px; color: var(--tx); padding: 8px; font-family: inherit; font-size: 13px; resize: vertical; }
  textarea:focus { outline: none; border-color: var(--ac); }
  .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
  .cancel { padding: 6px 16px; border-radius: 6px; border: none; background: var(--bdr); color: var(--tx-m); font-size: 13px; cursor: pointer; }
  .save { padding: 6px 16px; border-radius: 6px; border: none; background: var(--ac); color: white; font-size: 13px; cursor: pointer; }
  .save:hover { opacity: .9; }
</style>
