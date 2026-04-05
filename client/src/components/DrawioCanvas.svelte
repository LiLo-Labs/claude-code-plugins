<script>
  let { xml = '', dark = true, onchange, onselect, oncontextmenu: onctx, oncelladded, oncellremoved } = $props();

  let iframeEl = $state(null);
  let ready = $state(false);
  let loading = $state(true);
  let error = $state(null);
  let lastSentXml = '';
  let lastReceivedXml = '';

  // Build the draw.io embed URL — served from our own server
  const baseUrl = `${window.location.origin}/drawio/`;
  const params = new URLSearchParams({
    embed: '1',
    proto: 'json',
    spin: '1',
    libraries: '1',
    stealth: '1',
    noSaveBtn: '1',
    noExitBtn: '1',
    saveAndExit: '0',
    math: '0',
    dark: dark ? '1' : '0',
    grid: '0',
    configure: '1',
  });
  const iframeSrc = `${baseUrl}?${params}`;

  // Send a message to the draw.io iframe
  function postToDrawio(msg) {
    if (!iframeEl?.contentWindow) return;
    iframeEl.contentWindow.postMessage(JSON.stringify(msg), '*');
  }

  // Load XML into the editor
  function loadXml(xmlStr) {
    if (!ready || !xmlStr) return;
    if (xmlStr === lastSentXml || xmlStr === lastReceivedXml) return;
    lastSentXml = xmlStr;
    postToDrawio({ action: 'load', xml: xmlStr, autosave: 1 });
  }

  // Send configure message when draw.io asks for it
  function sendConfig() {
    postToDrawio({
      action: 'configure',
      config: {
        css: dark
          ? `.geDiagramBackdrop { background: #0d1117 !important; }
             .geDiagramContainer { background: #0d1117 !important; }
             .geDiagramContainer svg { background: #0d1117 !important; }
             .mxCellEditor { color: #e6edf3 !important; }
             .geBackgroundPage { background: #0d1117 !important; border: none !important; box-shadow: none !important; }`
          : '',
        defaultFonts: ['Inter', 'JetBrains Mono', 'Arial', 'Helvetica'],
      },
    });
  }

  // Handle messages from the draw.io iframe
  function handleMessage(event) {
    if (!iframeEl || event.source !== iframeEl.contentWindow) return;

    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    switch (msg.event) {
      case 'configure':
        sendConfig();
        break;

      case 'init':
        ready = true;
        loading = false;
        if (xml) {
          lastSentXml = xml;
          postToDrawio({ action: 'load', xml, autosave: 1 });
        }
        break;

      case 'load':
        if (!ready) {
          ready = true;
          loading = false;
        }
        if (msg.xml) {
          lastReceivedXml = msg.xml;
        }
        // Hook into selection model once draw.io is fully loaded
        setTimeout(hookDrawio, 300);
        break;

      case 'autosave':
        if (msg.xml && msg.xml !== lastSentXml) {
          lastReceivedXml = msg.xml;
          onchange?.(msg.xml);
        }
        break;

      case 'save':
        if (msg.xml) {
          lastReceivedXml = msg.xml;
          onchange?.(msg.xml);
        }
        break;

      case 'select': {
        // draw.io sends select events when cells are clicked
        const ids = msg.cells?.map(c => c.id).filter(Boolean) || [];
        onselect?.(ids);
        break;
      }

      case 'click': {
        // Fallback: some versions use click instead of select
        if (msg.cell?.id) {
          onselect?.([msg.cell.id]);
        }
        break;
      }
    }
  }

  // Hook into draw.io's internals via Draw.loadPlugin (same-origin iframe)
  let selectionHooked = false;
  function hookDrawio() {
    if (selectionHooked) return;
    try {
      const win = iframeEl?.contentWindow;
      if (!win?.Draw?.loadPlugin) {
        setTimeout(hookDrawio, 500);
        return;
      }
      win.Draw.loadPlugin(function(ui) {
        const graph = ui.editor.graph;
        if (!graph) return;
        selectionHooked = true;

        // Selection events → parent component
        graph.getSelectionModel().addListener('change', function() {
          const cells = graph.getSelectionCells();
          const ids = cells.map(c => c.id).filter(Boolean);
          onselect?.(ids);
        });

        // Dark mode: dark canvas, no page outlines, no grid
        if (dark) {
          if (typeof ui.setPageVisible === 'function') ui.setPageVisible(false);
          graph.background = '#0d1117';
          graph.gridEnabled = false;
          graph.container.style.backgroundColor = '#0d1117';
          // Style the diagram backdrop and container
          const backdrop = win.document.querySelector('.geDiagramBackdrop');
          if (backdrop) backdrop.style.backgroundColor = '#0d1117';
          const diagContainer = win.document.querySelector('.geDiagramContainer');
          if (diagContainer) diagContainer.style.backgroundColor = '#0d1117';
          // Main canvas SVG
          const svg = graph.container.querySelector('svg');
          if (svg) svg.style.backgroundColor = '#0d1117';
          graph.refresh();
        }
      });
    } catch {
      setTimeout(hookDrawio, 500);
    }
  }

  // Listen for postMessage events
  $effect(() => {
    window.addEventListener('message', handleMessage);
    return () => {
      window.removeEventListener('message', handleMessage);
      selectionCleanup?.();
      selectionCleanup = null;
    };
  });

  // React to xml prop changes — reload when the active tab switches
  let loadedXml = '';
  $effect(() => {
    const currentXml = xml;
    if (currentXml !== loadedXml) {
      loadedXml = currentXml;
      loadXml(currentXml);
    }
  });

  // React to dark mode changes — reload to apply
  $effect(() => {
    const _dark = dark;
    if (ready && xml) loadXml(xml);
  });
</script>

<div class="drawio-wrap">
  {#if loading}
    <div class="drawio-loading">
      <div class="spinner"></div>
      <span>Loading draw.io editor...</span>
    </div>
  {/if}
  {#if error}
    <div class="drawio-error">{error}</div>
  {/if}
  <iframe
    bind:this={iframeEl}
    src={iframeSrc}
    class="drawio-frame"
    class:hidden={loading}
    title="draw.io editor"
    frameborder="0"
    allow="clipboard-read; clipboard-write"
  ></iframe>
</div>

<style>
  .drawio-wrap {
    width: 100%;
    height: 100%;
    position: relative;
    background: var(--bg);
  }
  .drawio-frame {
    width: 100%;
    height: 100%;
    border: none;
  }
  .drawio-frame.hidden {
    opacity: 0;
  }
  .drawio-loading {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    color: var(--tx-d);
    font-size: 13px;
    z-index: 5;
  }
  .spinner {
    width: 24px;
    height: 24px;
    border: 2px solid var(--bdr);
    border-top-color: var(--ac);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  .drawio-error {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--or);
    font-size: 13px;
    z-index: 5;
  }
</style>
