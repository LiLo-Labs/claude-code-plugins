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

  onMount(async () => {
    // Load Excalidraw CSS
    await import('@excalidraw/excalidraw/index.css');

    const React = await import('react');
    const { createRoot } = await import('react-dom/client');
    const { Excalidraw } = await import('@excalidraw/excalidraw');

    root = createRoot(containerEl);

    const ExcalidrawWrapper = () => {
      return React.createElement(Excalidraw, {
        initialData: {
          elements: elements || [],
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
      excalidrawAPI.updateScene({ elements });
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
