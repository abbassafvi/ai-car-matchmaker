/**
 * Install a built MCP App bundle, and refuse to install a broken one.
 *
 * Shared by every app under `mcp-apps-ui/`. It was `booking-form/scripts/
 * install-bundle.mjs` through M4a, with its target path and source list
 * hardcoded; M4b needed the same guards for the checkout App, and two
 * copies of a correctness guard is two copies that drift. So the
 * *mechanism* lives here and each app declares its *configuration* in its
 * own package.json:
 *
 *     "mcpApp": {
 *       "target":   "../../mcp-services/booking/static/form.html",
 *       "sources":  ["src/main.ts", ...],
 *       "requires": ["ui/initialize"]
 *     }
 *
 * Run from the app's own directory (`npm run build` does this):
 *
 *     vite build && node ../scripts/install-bundle.mjs
 *
 * The guards matter because every failure they catch is silent:
 *
 * - **An external asset reference.** A build that emitted
 *   `assets/index-*.js` still produces a valid HTML file, still installs,
 *   still passes every Python test that only checks the resource returns
 *   *something* -- and renders as a blank iframe at demo time, because
 *   the host sandboxes the document without `allow-same-origin` so it has
 *   an opaque origin and cannot fetch a sibling file.
 * - **A missing handshake.** Without `ui/initialize` this is an iframe,
 *   not an MCP App, and the hackathon hard requirement it exists to
 *   satisfy is simply unmet while everything looks fine.
 * - **A stale artifact.** See the manifest section below.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const appRoot = process.cwd();
const sha256 = (text) => createHash("sha256").update(text, "utf8").digest("hex");

const fail = (message) => {
  console.error(`Refusing to install: ${message}`);
  process.exit(1);
};

/**
 * Configuration comes from the app's own package.json rather than from
 * CLI arguments, so that `npm run build` and a human running the script
 * by hand cannot disagree about where the bundle goes -- and so the
 * config is itself one of the hashed sources below.
 */
const pkg = JSON.parse(readFileSync(join(appRoot, "package.json"), "utf8"));
const config = pkg.mcpApp;
if (!config?.target || !Array.isArray(config.sources)) {
  fail(
    `${pkg.name} has no usable "mcpApp" config in package.json. It needs at ` +
      `least { "target": "...", "sources": [...] }.`,
  );
}

const source = resolve(appRoot, "dist", "index.html");
const target = resolve(appRoot, config.target);

/**
 * Derived, not configured. The convention is `form.html` ->
 * `form.build.json` beside it, and a separately-configured path is one
 * more thing that can point somewhere the test does not look.
 */
const manifestTarget = target.replace(/\.html$/, ".build.json");
if (manifestTarget === target) {
  fail(`target must end in .html, got ${config.target}`);
}

/**
 * Every input that can change the bundle's contents, listed explicitly
 * per app rather than globbed: adding a source file should be a
 * deliberate act that shows up in a diff, whereas a glob silently starts
 * covering a file nobody meant to include and silently stops covering one
 * that moved.
 *
 * This script is appended to the app's own list because it is genuinely
 * an input -- today it only copies, but the day it gains a transform, a
 * manifest that ignored it would go on claiming the artifact was current.
 */
const SHARED_SOURCES = ["../scripts/install-bundle.mjs"];
const sourceFiles = [...config.sources, ...SHARED_SOURCES];

const html = readFileSync(source, "utf8");

const externalRefs = [
  ...html.matchAll(/<script[^>]+\bsrc=["']([^"']+)["']/gi),
  ...html.matchAll(/<link[^>]+\bhref=["']([^"']+)["']/gi),
].map((match) => match[1]);

const remote = externalRefs.filter((ref) => !ref.startsWith("data:"));
if (remote.length > 0) {
  fail(
    `the bundle still references external assets, which a sandboxed\n` +
      `opaque-origin iframe cannot load:\n  ${remote.join("\n  ")}`,
  );
}

/**
 * `ui/initialize` is always required -- it is what separates an MCP App
 * from an iframe. An app may require more (checkout requires the name of
 * the tool it calls back, so a bundle that lost its submit path cannot
 * ship looking complete).
 */
const HANDSHAKE = "ui/initialize";
const required = [HANDSHAKE, ...(config.requires ?? [])];
const missing = required.filter((needle) => !html.includes(needle));
if (missing.length > 0) {
  // Two genuinely different failures, so two different messages. A single
  // message mentioning the handshake would be actively misleading when the
  // handshake is present and an app-specific string is what went missing
  // -- and a build error that misnames its own cause is the thing this
  // project keeps paying for.
  const reason = missing.includes(HANDSHAKE)
    ? `Without "${HANDSHAKE}" this is an iframe, not an MCP App, and the\n` +
      `hackathon MCP-App requirement is not met.`
    : `${pkg.name} declares these in package.json's "mcpApp".requires\n` +
      `because the App is not functional without them -- most often the name\n` +
      `of the server tool it calls back. Check that call still exists.`;
  fail(
    `the bundle does not contain ${missing.map((m) => `"${m}"`).join(", ")}.\n${reason}`,
  );
}

/**
 * The staleness manifest.
 *
 * The installed HTML is a committed build artifact and, until M4a Phase
 * C, nothing tied it to the source it came from. Demonstrated by the
 * audit: a marker appended to `src/main.ts` left all 83 mcp-services
 * tests green and never reached the shipped file. The bundle would have
 * been silently out of date in front of a judge, with no symptom but a
 * form quietly behaving like an older version of itself.
 *
 * `listings.json` has had a guard like this from the start (a test
 * asserts the committed file equals `generate()`), and the same idea
 * works here because the build is **byte-deterministic** -- rebuilding
 * from an unchanged tree reproduces the artifact exactly, re-measured
 * before this script was generalised. So hashing the inputs is a sound
 * proxy for "the artifact matches its source", and the Python tests
 * recompute it with no Node required.
 */
const sources = Object.fromEntries(
  sourceFiles.map((relative) => [
    relative,
    sha256(readFileSync(resolve(appRoot, relative), "utf8")),
  ]),
);

mkdirSync(dirname(target), { recursive: true });
writeFileSync(target, html);
writeFileSync(
  manifestTarget,
  JSON.stringify({ sources, bundle_sha256: sha256(html), bytes: html.length }, null, 2) + "\n",
);
console.log(`Installed ${(html.length / 1024).toFixed(0)} KB -> ${target}`);
console.log(`Wrote source manifest -> ${manifestTarget}`);
