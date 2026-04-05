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

  // Handle messages from the draw.io iframe
  function handleMessage(event) {
    if (!iframeEl || event.source !== iframeEl.contentWindow) return;

    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    switch (msg.event) {
      case 'init':
        // draw.io is ready — send the initial XML
        ready = true;
        loading = false;
        if (xml) {
          lastSentXml = xml;
          postToDrawio({ action: 'load', xml, autosave: 1 });
        }
        break;

      case 'load':
        // draw.io finished loading XML — marks readiness if not already
        if (!ready) {
          ready = true;
          loading = false;
        }
        // Capture the loaded XML as "received" to avoid echo
        if (msg.xml) {
          lastReceivedXml = msg.xml;
        }
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
        const ids = msg.cells?.map(c => c.id) || [];
        onselect?.(ids);
        break;
      }
    }
  }

  // Listen for postMessage events
  $effect(() => {
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
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
