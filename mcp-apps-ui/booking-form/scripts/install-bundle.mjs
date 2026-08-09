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
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "..", "dist", "index.html");
const projectRoot = resolve(here, "..");
const target = resolve(here, "..", "..", "..", "mcp-services", "booking", "static", "form.html");
const manifestTarget = resolve(dirname(target), "form.build.json");

/**
 * Every input that can change the bundle's contents. Listed explicitly
 * rather than globbed so that adding a source file is a deliberate act
 * that shows up in a diff — a glob would silently start covering a file
 * nobody meant to include, and silently stop covering one that moved.
 */
const SOURCE_FILES = [
  "src/main.ts",
  "src/styles.css",
  "index.html",
  "vite.config.ts",
  "package.json",
];

const sha256 = (text) => createHash("sha256").update(text, "utf8").digest("hex");

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

/**
 * The staleness manifest.
 *
 * `form.html` is a committed build artifact and, until this existed,
 * nothing tied it to the source it came from. Demonstrated by the M4a
 * Phase C audit: a marker appended to `src/main.ts` left all 83
 * mcp-services tests green and never reached the shipped file. The bundle
 * would have been silently out of date in front of a judge, and the only
 * symptom would have been a form behaving like an older version of itself.
 *
 * `listings.json` has had a guard like this from the start (a test asserts
 * the committed file equals `generate()`), and the same idea works here
 * because the build turned out to be byte-deterministic: rebuilding from
 * an unchanged tree reproduces `form.html` exactly. So a hash of the
 * inputs is a sound proxy for "the artifact matches its source", and
 * `mcp-services/tests/test_booking_server.py` recomputes it and fails when
 * the two drift — no Node required to run the check.
 */
const sources = Object.fromEntries(
  SOURCE_FILES.map((relative) => [
    relative,
    sha256(readFileSync(resolve(projectRoot, relative), "utf8")),
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
