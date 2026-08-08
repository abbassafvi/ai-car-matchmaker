/**
 * Copy the built single-file bundle to where the booking MCP server serves
 * it from, and refuse to install one that is not actually self-contained.
 *
 * The guard matters because the failure it catches is silent: a build that
 * emitted an external `assets/index-*.js` would still produce a valid HTML
 * file, still install cleanly, still pass every Python test that only
 * checks the resource returns *something* — and render as a blank iframe at
 * demo time, because the sandboxed document has an opaque origin and cannot
 * fetch it. Better to fail the build.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "..", "dist", "index.html");
const target = resolve(here, "..", "..", "..", "mcp-services", "booking", "static", "form.html");

const html = readFileSync(source, "utf8");

const externalRefs = [
  ...html.matchAll(/<script[^>]+\bsrc=["']([^"']+)["']/gi),
  ...html.matchAll(/<link[^>]+\bhref=["']([^"']+)["']/gi),
].map((match) => match[1]);

const remote = externalRefs.filter((ref) => !ref.startsWith("data:"));
if (remote.length > 0) {
  console.error(
    `Refusing to install: the bundle still references external assets, which a\n` +
      `sandboxed opaque-origin iframe cannot load:\n  ${remote.join("\n  ")}`,
  );
  process.exit(1);
}

if (!html.includes("ui/initialize")) {
  console.error(
    "Refusing to install: the bundle does not contain the MCP Apps handshake\n" +
      "(\"ui/initialize\"). Without it this is an iframe, not an MCP App, and\n" +
      "hackathon requirement #3 is not met.",
  );
  process.exit(1);
}

mkdirSync(dirname(target), { recursive: true });
writeFileSync(target, html);
console.log(`Installed ${(html.length / 1024).toFixed(0)} KB -> ${target}`);
