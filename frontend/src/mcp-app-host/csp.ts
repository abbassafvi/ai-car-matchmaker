/**
 * Turning the server's declared CSP into one the browser enforces.
 *
 * spec.md US3 AS1 requires the booking iframe to be sandboxed with a
 * deny-by-default CSP. Three separate things provide that, and it is worth
 * being precise about which does what, because two of them are easy to
 * mistake for the third:
 *
 * 1. **The iframe sandbox** (`allow-scripts`, deliberately *without*
 *    `allow-same-origin`) gives the document an opaque origin. That is why
 *    the bundle has to be self-contained -- it could not fetch a sibling
 *    asset even if it wanted to.
 * 2. **The bundle's own `<meta http-equiv>`**, baked in at build time.
 *    Defence in depth: it holds even in a host that ignores resource
 *    metadata entirely.
 * 3. **This module** — the *server's* declaration, carried on the `ui://`
 *    resource's `_meta.ui.csp`, applied by the host.
 *
 * Only (3) makes the declaration load-bearing. Without it the server could
 * declare anything at all and the rendered iframe would be identical, which
 * would leave US3 AS1 satisfied by coincidence: two independent hardcodings
 * that happen to agree. The backend goes out of its way to preserve this
 * metadata (`read_form_resource` bypasses the LangChain adapter, which
 * drops `_meta`) specifically so this function has something real to apply.
 *
 * The directive mapping below is **not invented**. ext-apps 1.7.5 does not
 * export a CSP builder, but its own zod schema documents what each field
 * means, and this follows it field by field:
 *
 *     connectDomains  → connect-src            (empty → no connections)
 *     resourceDomains → img-src, script-src, style-src, font-src, media-src
 *                                              (empty → no network resources)
 *     frameDomains    → frame-src              (empty → 'none')
 *     baseUriDomains  → base-uri               (empty → 'self')
 *
 * Injected as an extra `<meta>` rather than replacing the bundle's own.
 * Multiple CSP policies **intersect** — every one must allow a request — so
 * adding a policy can only ever restrict further. A host cannot accidentally
 * loosen the document's own guarantees this way, which is the property that
 * makes injection safe to do at all.
 */
export type CspDeclaration = {
  connectDomains?: string[];
  resourceDomains?: string[];
  frameDomains?: string[];
  baseUriDomains?: string[];
};

/**
 * Build the policy for a declaration.
 *
 * The subtlety is that "empty `resourceDomains`" means *no network
 * resources*, not *no resources*. `script-src`/`style-src` therefore keep
 * `'unsafe-inline'`: a single self-contained document whose script and
 * styles are inline is what an MCP App **is**, and dropping it would blank
 * every bundle. With `default-src 'none'` beside them, inline code can
 * still reach nothing.
 */
export function buildCsp(declaration: CspDeclaration | undefined): string {
  const list = (domains: string[] | undefined, extra: string[] = []): string => {
    const parts = [...extra, ...(domains ?? [])];
    return parts.length > 0 ? parts.join(" ") : "'none'";
  };

  const resources = declaration?.resourceDomains;
  const base = declaration?.baseUriDomains;

  return [
    "default-src 'none'",
    // 'unsafe-inline' is the App itself; the domains are what it may fetch.
    `script-src ${list(resources, ["'unsafe-inline'"])}`,
    `style-src ${list(resources, ["'unsafe-inline'"])}`,
    // data: so an App can inline its own icons -- the only way it can have
    // any, since it cannot fetch one.
    `img-src ${list(resources, ["data:"])}`,
    `font-src ${list(resources, ["data:"])}`,
    `media-src ${list(resources)}`,
    `connect-src ${list(declaration?.connectDomains)}`,
    `frame-src ${list(declaration?.frameDomains)}`,
    // 'self' inside an opaque origin is the document itself, which is the
    // spec's documented default for an omitted baseUriDomains.
    `base-uri ${base && base.length > 0 ? base.join(" ") : "'self'"}`,
    "form-action 'none'",
    // ⚠️ `frame-ancestors` is deliberately absent, and its absence is the
    // honest state rather than a gap.
    //
    // It used to be listed here, on a belt-and-braces argument about an App
    // never framing the page that hosts it. But this policy is delivered as
    // a `<meta http-equiv>` tag, and the CSP spec says `frame-ancestors` is
    // ignored in meta-delivered policies -- Chromium says so out loud, once
    // per App load: "The Content Security Policy directive 'frame-ancestors'
    // is ignored when delivered via a <meta> element." So the directive was
    // never enforcing anything; it was a comment that looked like a control,
    // and it was the only thing keeping the e2e suite's zero-console-errors
    // assertion red.
    //
    // What actually provides the guarantee is the sandbox attribute in
    // McpAppFrame (`APP_SANDBOX` below withholds `allow-same-origin`), which
    // gives the document an opaque origin -- it cannot reach this page, its
    // storage, or its DOM. Re-adding this line would restore the warning
    // without restoring any protection; enforcing it for real needs a
    // response header, which a `srcdoc` document has no room for.
  ].join("; ");
}

/**
 * Insert the policy as the first thing in `<head>`.
 *
 * First because a `<meta http-equiv="Content-Security-Policy">` governs only
 * what follows it in the document; placed after a script it would not apply
 * to that script. Prepending the whole document covers a bundle with no
 * `<head>`, where the browser synthesises one around whatever comes first.
 */
export function withCsp(html: string, declaration: CspDeclaration | undefined): string {
  const tag = `<meta http-equiv="Content-Security-Policy" content="${buildCsp(declaration)}">`;
  const head = html.match(/<head[^>]*>/i);
  if (!head) return tag + html;
  const at = html.indexOf(head[0]) + head[0].length;
  return html.slice(0, at) + tag + html.slice(at);
}

/**
 * The `sandbox` attribute for an App's iframe.
 *
 * `allow-same-origin` is **never** included, whatever a resource asks for.
 * Granting it to a `srcdoc` document would give it *our* origin, and with it
 * our `localStorage` (which holds the session id), our cookies, and reach
 * into this page's DOM. No declaration a server could make would justify
 * that, so this is a constant rather than something derived from `_meta`.
 *
 * `allow-forms` is present because the App is a form; submission is
 * intercepted by its own script, and `form-action 'none'` above means a
 * native submit can go nowhere regardless.
 */
export const APP_SANDBOX = "allow-scripts allow-forms";
