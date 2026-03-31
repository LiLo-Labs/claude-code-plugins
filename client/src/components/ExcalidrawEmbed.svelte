<script>
  /**
   * ExcalidrawEmbed — mounts the Excalidraw React component inside Svelte.
   * Uses React.createRoot to bridge frameworks.
   */
  import { onMount, onDestroy } from 'svelte';

  let { elements = [], onchange, dark = true } = $props();

  let containerEl = $state(null);
  let root = null;
  let excalidrawAPI = null;

  /**
   * Convert label objects on shapes into proper bound text elements.
   * Excalidraw's React component doesn't support the `label` shorthand
   * that the MCP server uses — it needs explicit text elements with
   * containerId + boundElements linkage.
   */
  function expandLabels(els) {
    const expanded = [];
    for (const el of els) {
      if (el.label && (el.type === 'rectangle' || el.type === 'ellipse' || el.type === 'diamond')) {
        const textId = el.id + '_label';
        // Add shape with boundElements reference
        expanded.push({
          ...el,
          label: undefined,
          boundElements: [...(el.boundElements || []), { type: 'text', id: textId }],
        });
        // Add bound text element
        expanded.push({
          type: 'text',
          id: textId,
          x: el.x + el.width / 2,
          y: el.y + el.height / 2,
          width: el.width - 20,
          height: el.label.fontSize ? el.label.fontSize + 8 : 24,
          text: el.label.text || '',
          fontSize: el.label.fontSize || 16,
          fontFamily: el.label.fontFamily || 2,
          strokeColor: el.strokeColor || '#e5e5e5',
          textAlign: 'center',
          verticalAlign: 'middle',
          containerId: el.id,
          angle: 0,
          opacity: 100,
        });
      } else {
        expanded.push(el);
      }
    }
    return expanded;
  }

  onMount(async () => {
    // Load Excalidraw CSS
    await import('@excalidraw/excalidraw/index.css');

    const React = await import('react');
    const { createRoot } = await import('react-dom/client');
    const { Excalidraw } = await import('@excalidraw/excalidraw');

    root = createRoot(containerEl);
    const processedElements = expandLabels(elements || []);

    const ExcalidrawWrapper = () => {
      return React.createElement(Excalidraw, {
        initialData: {
          elements: processedElements,
          appState: {
            theme: dark ? 'dark' : 'light',
            viewBackgroundColor: dark ? '#0f1117' : '#ffffff',
          },
        },
        theme: dark ? 'dark' : 'light',
        excalidrawAPI: (api) => { excalidrawAPI = api; },
        onChange: (els) => {
          onchange?.(els);
        },
        UIOptions: {
          canvasActions: {
            saveToActiveFile: false,
            loadScene: false,
            export: { saveFileToDisk: true },
          },
        },
      });
    };

    root.render(React.createElement(ExcalidrawWrapper));
  });

  onDestroy(() => {
    root?.unmount();
  });

  // Update elements when prop changes
  $effect(() => {
    if (excalidrawAPI && elements?.length > 0) {
      excalidrawAPI.updateScene({ elements: expandLabels(elements) });
    }
  });
</script>

<div class="excalidraw-container" bind:this={containerEl}></div>

<style>
  .excalidraw-container {
    width: 100%;
    height: 100%;
    min-height: 400px;
    position: relative;
  }
  .excalidraw-container :global(.excalidraw) {
    width: 100%;
    height: 100%;
  }
</style>
