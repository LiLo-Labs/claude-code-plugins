export default {
  onwarn(warning, handler) {
    // Suppress a11y warnings for SVG canvas elements — this is a drawing app, not a web page
    if (warning.code.startsWith('a11y')) return;
    handler(warning);
  },
};
