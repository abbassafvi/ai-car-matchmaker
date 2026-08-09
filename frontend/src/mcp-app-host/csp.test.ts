/**
 * The host's CSP derivation (M4a Phase D).
 *
 * Worth testing rather than eyeballing for two reasons. First, the mapping
 * from `_meta.ui.csp` to directives is **read off the MCP Apps spec**, not
 * invented — ext-apps 1.7.5 documents each field in its own zod schema but
 * exports no builder, so this is our transcription of someone else's
 * contract and transcriptions drift. Second, the failure mode is silent in
 * both directions: too strict and the form renders blank, too loose and
 * spec.md US3 AS1 is quietly unmet while everything still looks fine.
 *
 * The empty declaration is the one that actually ships, so it gets the most
 * attention: the booking resource declares `connectDomains: []` and
 * `resourceDomains: []`.
 */
import { describe, expect, it } from "vitest";

import { APP_SANDBOX, buildCsp, withCsp } from "./csp";

const directives = (declaration?: Parameters<typeof buildCsp>[0]) =>
  Object.fromEntries(
    buildCsp(declaration)
      .split("; ")
      .map((d) => {
        const [name, ...rest] = d.split(" ");
        return [name, rest.join(" ")];
      }),
  );

describe("buildCsp", () => {
  it("denies everything by default when the declaration is empty", () => {
    const d = directives({ connectDomains: [], resourceDomains: [] });
    expect(d["default-src"]).toBe("'none'");
    expect(d["connect-src"]).toBe("'none'");
    expect(d["media-src"]).toBe("'none'");
    expect(d["frame-src"]).toBe("'none'");
    expect(d["form-action"]).toBe("'none'");
  });

  it("treats an absent declaration exactly like an empty one", () => {
    // "Empty or omitted → secure default", per the spec's own wording for
    // every field. A host that fell back to permissive on a missing
    // declaration would be the worst possible reading.
    expect(buildCsp(undefined)).toBe(
      buildCsp({ connectDomains: [], resourceDomains: [] }),
    );
  });

  it("still allows the inline script and style that make an App an App", () => {
    // "No network resources" is not "no resources". A single self-contained
    // document whose script and styles are inline is what an MCP App *is*;
    // dropping 'unsafe-inline' blanks every bundle. With default-src 'none'
    // beside it, inline code can still reach nothing.
    const d = directives({ resourceDomains: [] });
    expect(d["script-src"]).toBe("'unsafe-inline'");
    expect(d["style-src"]).toBe("'unsafe-inline'");
  });

  it("lets an App inline its own images and fonts as data URIs", () => {
    const d = directives({});
    expect(d["img-src"]).toBe("data:");
    expect(d["font-src"]).toBe("data:");
  });

  it("maps resourceDomains onto every resource directive the spec lists", () => {
    // img-src, script-src, style-src, font-src, media-src — quoted from the
    // schema. Getting this partially right is the likely mistake, so all
    // five are asserted.
    const d = directives({ resourceDomains: ["https://cdn.example.com"] });
    for (const directive of ["img-src", "script-src", "style-src", "font-src", "media-src"]) {
      expect(d[directive]).toContain("https://cdn.example.com");
    }
    expect(d["connect-src"]).toBe("'none'");
  });

  it("maps connectDomains onto connect-src only", () => {
    const d = directives({ connectDomains: ["https://api.example.com"] });
    expect(d["connect-src"]).toBe("https://api.example.com");
    expect(d["img-src"]).toBe("data:");
  });

  it("defaults base-uri to 'self' rather than 'none' when omitted", () => {
    // The one field whose documented default is not 'none'.
    expect(directives({})["base-uri"]).toBe("'self'");
    expect(directives({ baseUriDomains: ["https://x.example.com"] })["base-uri"])
      .toBe("https://x.example.com");
  });
});

describe("withCsp", () => {
  const html = "<!doctype html><html><head><title>t</title></head><body>b</body></html>";

  it("puts the policy first in <head>, before anything it must govern", () => {
    // A meta CSP only governs what follows it. Injected after a script, it
    // would not apply to that script -- which is the whole point.
    const out = withCsp(html, {});
    expect(out.indexOf("Content-Security-Policy")).toBeLessThan(out.indexOf("<title>"));
  });

  it("keeps the document's own policy rather than replacing it", () => {
    // Multiple policies intersect, so adding one can only restrict further.
    // That property is why injecting is safe; if this ever started
    // replacing, a permissive server declaration could loosen a bundle's
    // own guarantees.
    const withOwn = html.replace(
      "<head>",
      `<head><meta http-equiv="Content-Security-Policy" content="default-src 'none'">`,
    );
    const out = withCsp(withOwn, {});
    expect(out.match(/Content-Security-Policy/g)).toHaveLength(2);
  });

  it("still applies a policy to a document with no head", () => {
    expect(withCsp("<p>bare</p>", {})).toMatch(/^<meta http-equiv="Content-Security-Policy"/);
  });
});

describe("the sandbox", () => {
  it("never grants allow-same-origin", () => {
    // A srcdoc document given allow-same-origin inherits *our* origin, and
    // with it localStorage (which holds the session id), our cookies, and
    // reach into this page's DOM. No server declaration could justify it,
    // which is why it is a constant and not derived from _meta.
    expect(APP_SANDBOX).not.toContain("allow-same-origin");
    expect(APP_SANDBOX).toContain("allow-scripts");
  });
});
