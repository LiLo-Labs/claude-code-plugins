<script>
  /**
   * ExcalidrawEmbed — iframes the interactive-drawer viewer.
   * The MCP server handles element creation/formatting via create_view.
   * We just iframe its viewer URL for the given session.
   *
   * Requires interactive-drawer running in web mode on port 3001:
   *   npx interactive-drawer --port 3001
   */
  let { viewerUrl = '', dark = true } = $props();

  // Default to the interactive-drawer viewer base
  const src = viewerUrl || 'http://localhost:3001';
</script>

<div class="excalidraw-container">
  <iframe
    {src}
    title="Excalidraw editor"
    frameborder="0"
  ></iframe>
</div>

<style>
  .excalidraw-container {
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
