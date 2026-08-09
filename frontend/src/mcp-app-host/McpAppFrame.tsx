/**
 * T034 — the MCP Apps host, satisfying hackathon requirement #3.
 *
 * The booking form is a real MCP App: a `ui://` resource rendered in a
 * sandboxed iframe that speaks the MCP Apps protocol over postMessage. This
 * component is the host half of that conversation, built on the official
 * `AppBridge` rather than a hand-rolled handshake — the same reasoning as
 * the View half (T032): a protocol implemented from prose is exactly the
 * "looks right, never ran" failure this project keeps paying for.
 *
 * **There is no MCP client in the browser, deliberately.** `AppBridge`
 * accepts a `null` client and exposes `oncalltool` as a public setter, so
 * the host can intercept the App's `tools/call` and tunnel it over the
 * WebSocket the chat already uses. The alternatives were both worse: a
 * second MCP client here would need CORS and would let the form submit
 * straight to `mcp-services`, bypassing agent-backend entirely — while the
 * `FORM_FILLING → AWAITING_PAYMENT` transition and the `Booking` record
 * live in the backend's checkpointer. One wire, one source of session
 * truth.
 *
 * Ordering is load-bearing and is the easiest thing to get wrong:
 *
 *     connect() → View sends ui/initialize → View sends initialized
 *                → oninitialized fires → sendToolInput → sendToolResult
 *
 * ext-apps states `sendToolInput` "is sent exactly once and is **required
 * before** `sendToolResult`". Send the result first, or skip the input, and
 * the View's `ontoolresult` never runs: the iframe renders its empty state
 * and sits there looking like a broken form with nothing in the console.
 */
import { useEffect, useRef } from "react";
// The **host** half lives on the `/app-bridge` subpath. The package root
// is the *View* side (the `App` class the booking bundle imports), so
// importing AppBridge from the root fails with "has no exported member" --
// worth knowing, because the two halves of this protocol look symmetrical
// and are not.
import {
  AppBridge,
  PostMessageTransport,
  buildAllowAttribute,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import type { CallToolRequest } from "@modelcontextprotocol/sdk/types.js";
import type { McpUiStyles } from "@modelcontextprotocol/ext-apps/app-bridge";

import { APP_SANDBOX, withCsp } from "./csp";
import type { McpAppEnvelope } from "./types";

export type CallServerTool = (
  name: string,
  args: Record<string, unknown>,
) => Promise<Record<string, unknown>>;

type Props = {
  envelope: McpAppEnvelope;
  /** Tunnels the App's tool call over the chat WebSocket. */
  onCallTool: CallServerTool;
  /** Called when the user clicks the cancel/dismiss button. */
  onCancel?: () => void;
};

const HOST_INFO = { name: "ai-car-matchmaker", version: "1.0.0" };

/** What this host is prepared to do for a View. `serverTools` is the one
 * that matters: it advertises that `callServerTool` will be answered. No
 * `openLinks` — a booking form has no business navigating the user away,
 * which is the whole point of requirement #3. */
const HOST_CAPABILITIES = { serverTools: {}, logging: {} };

/**
 * The chat shell's own palette, handed to the App as context.
 *
 * The names are a fixed enum in the MCP Apps spec, not free-form. That is
 * load-bearing: an earlier attempt used `--color-background`, which
 * TypeScript rejected and which would otherwise have been set on the
 * document, ignored by the stylesheet, and left the form looking untouched
 * while appearing to be themed. These are exactly the names
 * `booking-form/src/styles.css` reads.
 *
 * `satisfies Partial<...>` then a cast: the generated `.d.ts` marks all ~70
 * variables **required**, but the runtime zod schema accepts any subset --
 * verified by parsing one. So the cast works around over-strict generated
 * types rather than a real protocol constraint, and `satisfies` keeps the
 * key-name checking, which is the part that caught the mistake above.
 */
const THEME_VARIABLES = {
  "--color-background-primary": "#ffffff",
  "--color-background-secondary": "#f8fafc",
  "--color-background-inverse": "#0b63ce",
  "--color-text-primary": "#1c2024",
  "--color-text-secondary": "#7b8794",
  "--color-text-inverse": "#ffffff",
  "--color-border-primary": "#d3dae2",
  "--color-ring-primary": "#0b63ce",
} satisfies Partial<McpUiStyles>;

export default function McpAppFrame({ envelope, onCallTool, onCancel }: Props) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  // The callback is read at call time rather than captured, so the bridge
  // does not have to be torn down and rebuilt (losing the App's state, and
  // everything the user has typed) every time the parent re-renders.
  const callRef = useRef(onCallTool);
  callRef.current = onCallTool;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame?.contentWindow) return;

    const bridge = new AppBridge(null, HOST_INFO, HOST_CAPABILITIES);
    let closed = false;

    bridge.oncalltool = async (params: CallToolRequest["params"]) => {
      const structuredContent = await callRef.current(
        params.name,
        (params.arguments ?? {}) as Record<string, unknown>,
      );
      // `content` is required by the MCP CallToolResult shape even when
      // everything meaningful is in `structuredContent` -- which it is
      // here, because that is the typed channel the App reads.
      return { content: [], structuredContent };
    };

    // Theme travels host → View as *context*, not as CSS: the iframe
    // cannot read our stylesheet across an opaque origin. `main.ts` stamps
    // `data-theme` from this and sets each variable as an inline style.
    //
    // The names are a fixed enum in the MCP Apps spec, not free-form --
    // TypeScript rejected an earlier attempt at `--color-background`, which
    // would otherwise have been set, ignored, and left the form looking
    // untouched while appearing to be themed. They are also exactly the
    // names `booking-form/src/styles.css` reads. Values are the chat
    // shell's own, so the iframe does not look pasted in.
    bridge.setHostContext({
      theme: "light",
      styles: { variables: THEME_VARIABLES as McpUiStyles },
    });

    // The App is built with ext-apps' `autoResize`, so it reports its own
    // content height. Honouring it is what stops the form being either
    // clipped or floating in a fixed box two thirds empty -- the host owns
    // the element, so only the host can act on it. Capped in CSS rather
    // than here, so a tall form scrolls inside its panel instead of pushing
    // the composer off screen.
    bridge.onsizechange = ({ height }) => {
      if (closed || !height) return;
      frame.style.height = `${Math.ceil(height)}px`;
    };

    bridge.oninitialized = () => {
      if (closed) return;
      // Required before the result -- see the module docstring. Awaited in
      // order rather than fired together, because "sent exactly once and
      // required before" is about arrival order, not call order.
      void (async () => {
        await bridge.sendToolInput(envelope.toolInput);
        // `content` is required by the MCP CallToolResult shape; the App
        // reads `structuredContent`, which is the typed channel, so an
        // empty content list is what ext-apps' own manual-handler example
        // uses. The backend does not send it -- adding it here keeps the
        // envelope to what is actually consumed.
        if (!closed) {
          await bridge.sendToolResult({ content: [], ...envelope.toolResult });
        }
      })();
    };

    const transport = new PostMessageTransport(
      frame.contentWindow,
      frame.contentWindow,
    );
    void bridge.connect(transport);

    return () => {
      closed = true;
      void bridge.close();
    };
    // Keyed on the document and the payload: a *different* booking (another
    // car, or the form reopened) is a new App and must get a new bridge.
    // Re-running on every render would reset the form under the user.
  }, [envelope.resource.html, envelope.toolResult]);

  return (
    <div className="mcp-app" data-app={envelope.app} data-testid="mcp-app-frame">
      {onCancel && (
        <button className="mcp-app-cancel" onClick={onCancel} aria-label="Cancel">
          {"\u2715"}
        </button>
      )}
      <iframe
        ref={frameRef}
        title="Booking form"
        // srcdoc, not a URL: the resource arrives as a string over the
        // WebSocket and there is nothing to fetch it from. Combined with a
        // sandbox that withholds allow-same-origin, the document gets an
        // opaque origin -- it cannot reach this page, its storage, or the
        // network. See csp.ts for which layer provides what.
        srcDoc={withCsp(envelope.resource.html, envelope.resource.meta?.ui?.csp)}
        sandbox={APP_SANDBOX}
        // ext-apps' own mapping from declared permissions to a
        // Permission-Policy string, rather than a hand-rolled one. The
        // booking App declares `permissions: {}`, so this is "" -- every
        // powerful feature denied, which is also the right reading of an
        // absent declaration: never grant a capability nobody asked for.
        allow={buildAllowAttribute(envelope.resource.meta?.ui?.permissions)}
        referrerPolicy="no-referrer"
      />
    </div>
  );
}
