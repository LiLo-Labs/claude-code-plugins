<script>
  /**
   * DrawioEmbed — embeds draw.io editor in an iframe.
   * Communicates via postMessage protocol.
   * Loads diagram XML, receives changes via autosave.
   */
  import { onMount, onDestroy } from 'svelte';

  let { xml = '', onchange, dark = true } = $props();

  let iframeEl = $state(null);
  let ready = $state(false);

  const baseUrl = 'https://embed.diagrams.net/';
  const params = new URLSearchParams({
    embed: '1',
    proto: 'json',
    spin: '1',
    libraries: '1',
    noExitBtn: '1',
    saveAndExit: '0',
    noSaveBtn: '1',
    // Minimal UI — hide chrome, keep essential tools
    ui: 'min',
    toolbar: '0',
    pages: '0',
    footer: '0',
  });
  if (dark) params.set('dark', '1');

  const src = `${baseUrl}?${params}`;

  function handleMessage(event) {
    if (!event.data || typeof event.data !== 'string') return;
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.event === 'init') {
      ready = true;
      // Load the diagram
      iframeEl?.contentWindow?.postMessage(JSON.stringify({
        action: 'load',
        xml: xml || '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>',
        autosave: 1,
      }), '*');
    }

    if (msg.event === 'autosave' || msg.event === 'save') {
      onchange?.(msg.xml);
    }
  }

  onMount(() => {
    window.addEventListener('message', handleMessage);
  });

  onDestroy(() => {
    window.removeEventListener('message', handleMessage);
  });

  // Re-load when xml prop changes externally
  $effect(() => {
    if (ready && xml && iframeEl?.contentWindow) {
      iframeEl.contentWindow.postMessage(JSON.stringify({
        action: 'merge',
        xml,
      }), '*');
    }
  });
</script>

<div class="drawio-container">
  <iframe
    bind:this={iframeEl}
    {src}
    title="draw.io editor"
    frameborder="0"
  ></iframe>
</div>

<style>
  .drawio-container {
    width: 100%;
    height: 100%;
    min-height: 400px;
    position: relative;
  }
  iframe {
    width: 100%;
    height: 100%;
    border: none;
    position: absolute;
    inset: 0;
  }
</style>
