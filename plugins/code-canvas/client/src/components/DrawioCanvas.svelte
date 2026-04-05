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
    dark: '0',
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
        css: dark ? darkChromeCSS : '',
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
        // Start applying dark chrome as soon as draw.io initializes
        if (dark) setTimeout(applyDarkChrome, 500);
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
        // Re-apply dark chrome after each load (UI may have been rebuilt)
        if (dark) { chromeHidden = false; setTimeout(applyDarkChrome, 300); }
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

  // Programmatic edge routing: set exit/entry points based on relative positions
  function routeEdges(graph) {
    const model = graph.getModel();

    // Helper: get absolute center of a cell (walking parent chain)
    function absCenter(cell) {
      const g = graph.getCellGeometry(cell);
      if (!g) return null;
      let x = g.x + g.width / 2, y = g.y + g.height / 2;
      let p = model.getParent(cell);
      while (p && p.geometry) { x += p.geometry.x; y += p.geometry.y; p = model.getParent(p); }
      return { x, y };
    }

    model.beginUpdate();
    try {
      for (const id of Object.keys(model.cells)) {
        const cell = model.cells[id];
        if (!cell.edge || !cell.source || !cell.target) continue;
        if (cell.source === cell.target) continue;

        let styleStr = model.getStyle(cell) || '';

        // Skip edges that already have explicit exit/entry in the XML
        if (styleStr.includes('exitX=') && styleStr.includes('entryX=')) continue;

        const sc = absCenter(cell.source), tc = absCenter(cell.target);
        if (!sc || !tc) continue;

        const dx = tc.x - sc.x, dy = tc.y - sc.y;
        const absDx = Math.abs(dx), absDy = Math.abs(dy);

        // Check if source and target are in different parents (cross-boundary)
        const sameParent = model.getParent(cell.source) === model.getParent(cell.target);

        let exitX, exitY, entryX, entryY;
        if (absDy > absDx * 0.5) {
          if (dy > 0) { exitX = 0.5; exitY = 1; entryX = 0.5; entryY = 0; }
          else        { exitX = 0.5; exitY = 0; entryX = 0.5; entryY = 1; }
        } else if (absDx > absDy * 0.5) {
          if (dx > 0) { exitX = 1; exitY = 0.5; entryX = 0; entryY = 0.5; }
          else        { exitX = 0; exitY = 0.5; entryX = 1; entryY = 0.5; }
        } else {
          exitX = dx > 0 ? 1 : 0; exitY = dy > 0 ? 1 : 0;
          entryX = dx > 0 ? 0 : 1; entryY = dy > 0 ? 0 : 1;
        }

        // Strip any partial exit/entry
        styleStr = styleStr.replace(/exit[XY]=[^;]*(;|$)/g, '')
                           .replace(/entry[XY]=[^;]*(;|$)/g, '')
                           .replace(/;;+/g, ';').replace(/^;|;$/g, '');

        styleStr += `;exitX=${exitX};exitY=${exitY};entryX=${entryX};entryY=${entryY}`;

        // Only add orthogonal for same-parent edges; cross-boundary edges stay curved
        if (sameParent && !styleStr.includes('edgeStyle=') && !styleStr.includes('curved=')) {
          styleStr += ';edgeStyle=orthogonalEdgeStyle';
        }

        model.setStyle(cell, styleStr);
      }
    } finally {
      model.endUpdate();
    }
  }

  // Hook into draw.io's internals via Draw.loadPlugin (same-origin iframe)
  let selectionHooked = false;
  let chromeHidden = false;

  const darkChromeCSS = `
    body, .geEditor { background: #0d1117 !important; }
    .geMenubarContainer, .geToolbarContainer, .geTabContainer,
    .geSidebarFooter, .geFormatContainer, .geHsplit { display: none !important; }
    .geDiagramBackdrop { background: #0d1117 !important; }
    .geDiagramContainer { background: #0d1117 !important; top: 0 !important; right: 0 !important; }
    .geDiagramContainer svg { background: #0d1117 !important; }
    .geBackgroundPage { background: #0d1117 !important; border: none !important; box-shadow: none !important; }
    .mxCellEditor { color: #e6edf3 !important; }
    .geSidebarContainer:not(.geFormatContainer) { background: #161b22 !important; border-color: #30363d !important; color: #c9d1d9 !important; }
    .geSidebarContainer:not(.geFormatContainer) .geTitle { background: #0d1117 !important; border-color: #30363d !important; color: #c9d1d9 !important; }
    .geSidebarContainer:not(.geFormatContainer) a { color: #c9d1d9 !important; }
    .geSidebarContainer:not(.geFormatContainer) input { background: #21262d !important; color: #c9d1d9 !important; border-color: #30363d !important; }
    .mxWindow { background: #161b22 !important; border-color: #30363d !important; }
    .mxWindow * { color: #c9d1d9 !important; }
    .mxWindowTitle { background: #21262d !important; color: #e6edf3 !important; }
  `;

  function applyDarkChrome() {
    if (chromeHidden) return;
    // Find iframe via DOM query (avoids Svelte binding timing issues)
    const iframe = document.querySelector('iframe.drawio-frame');
    if (!iframe) return;
    let doc;
    try { doc = iframe.contentDocument || iframe.contentWindow?.document; } catch { return; }
    if (!doc?.head || !doc.querySelector('.geMenubarContainer')) return;

    chromeHidden = true;

    // Inject CSS + hide chrome elements via inline script in iframe
    const script = doc.createElement('script');
    script.textContent = '(function(){var css=document.createElement("style");css.textContent='
      + JSON.stringify(darkChromeCSS)
      + ';document.head.appendChild(css);'
      + '[".geMenubarContainer",".geToolbarContainer",".geTabContainer",'
      + '".geSidebarFooter",".geHsplit",".geFormatContainer"].forEach(function(s){'
      + 'document.querySelectorAll(s).forEach(function(e){e.style.display="none"})});})();';
    doc.head.appendChild(script);
  }

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

        // Fix edge routing: compute exit/entry points from relative positions
        routeEdges(graph);

        // Dark mode: dark canvas, no page outlines, no grid
        if (dark) {
          if (typeof ui.setPageVisible === 'function') ui.setPageVisible(false);
          graph.background = '#0d1117';
          graph.gridEnabled = false;
          graph.container.style.backgroundColor = '#0d1117';
          graph.refresh();
        }
      });

      // Apply dark chrome independently — don't wait for Draw.loadPlugin callback
      if (dark) applyDarkChrome();
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

  // Listen for iframe load event to apply dark chrome
  $effect(() => {
    const el = iframeEl;
    if (!dark || !el) return;
    const onLoad = () => {
      let attempts = 0;
      const poll = () => {
        if (chromeHidden || attempts++ > 40) return;
        applyDarkChrome();
        if (!chromeHidden) setTimeout(poll, 500);
      };
      setTimeout(poll, 500);
    };
    el.addEventListener('load', onLoad);
    // Also try immediately in case already loaded
    onLoad();
    return () => el.removeEventListener('load', onLoad);
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
