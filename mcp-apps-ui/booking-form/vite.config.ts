import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

/**
 * One HTML file out, everything inlined.
 *
 * This is a hard constraint, not an optimisation. The host renders this
 * document in an iframe sandboxed with `allow-scripts` but WITHOUT
 * `allow-same-origin`, so it has an opaque origin: it cannot fetch a
 * sibling script, stylesheet or font from mcp-services, and the ui://
 * resource is a single text blob anyway. A build that emitted
 * `assets/index-*.js` would produce a blank form with a console full of
 * blocked requests.
 *
 * `install-bundle.mjs` then copies the result to
 * mcp-services/booking/static/form.html, which is committed — the same
 * pattern as data/listings.json: a generated artifact checked in for
 * reproducibility, with a test guarding it.
 */
export default defineConfig({
  plugins: [viteSingleFile()],
  build: {
    target: "es2022",
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000,
    chunkSizeWarningLimit: 2000,
  },
});
