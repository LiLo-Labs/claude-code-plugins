<script>
  /**
   * DrawioEmbed — embeds draw.io editor in an iframe.
   * Communicates via postMessage protocol.
   * Reloads diagram when xml prop changes (tab switch).
   */
  import { onMount, onDestroy } from 'svelte';

  let { xml = '', onchange, onselect, dark = true } = $props();

  let iframeEl = $state(null);
  let ready = $state(false);
  let loadedXml = '';  // track what we last loaded to avoid re-sends

  const baseUrl = 'https://embed.diagrams.net/';
  const params = new URLSearchParams({
    embed: '1',
    proto: 'json',
    spin: '1',
    configure: '1',
    // Sketch mode — minimal chrome, just canvas + floating toolbar
    ui: 'sketch',
    noExitBtn: '1',
    saveAndExit: '0',
    noSaveBtn: '1',
    pages: '0',
    grid: '0',
  });
  if (dark) params.set('dark', '1');

  const src = `${baseUrl}?${params}`;

  function loadDiagram(xmlContent) {
    if (!iframeEl?.contentWindow) return;
    loadedXml = xmlContent;
    iframeEl.contentWindow.postMessage(JSON.stringify({
      action: 'load',
      xml: xmlContent || '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>',
      autosave: 1,
    }), '*');
  }

  function handleMessage(event) {
    if (!event.data || typeof event.data !== 'string') return;
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.event === 'configure') {
      iframeEl?.contentWindow?.postMessage(JSON.stringify({
        action: 'configure',
        config: {
          // Hide shape library and format panels
          defaultLibraries: '',
          enabledLibraries: [],
          libraries: [],
          css: '.geFooterContainer { display: none !important; } .geFormatContainer { display: none !important; }',
        },
      }), '*');
    }

    if (msg.event === 'init') {
      ready = true;
      loadDiagram(xml);
    }

    if (msg.event === 'autosave' || msg.event === 'save') {
      loadedXml = msg.xml;
      onchange?.(msg.xml);
    }

    if (msg.event === 'select') {
      const ids = msg.selected || [];
      onselect?.(ids);
    }
  }

  onMount(() => {
    window.addEventListener('message', handleMessage);
  });

  onDestroy(() => {
    window.removeEventListener('message', handleMessage);
  });

  // Reload when xml prop changes (tab switch)
  $effect(() => {
    if (ready && xml !== loadedXml) {
      loadDiagram(xml);
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
