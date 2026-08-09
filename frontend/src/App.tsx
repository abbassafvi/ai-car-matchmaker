import { useCallback, useEffect, useRef, useState } from "react";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { A2uiSurface, basicCatalog } from "@a2ui/react/v0_9";
import McpAppFrame from "./mcp-app-host/McpAppFrame";
import type { McpAppEnvelope } from "./mcp-app-host/types";
import "./app.css";
import "./a2ui-theme.css";
// Note: @a2ui/react@0.10.2's "./styles/structural.css" export points at a
// file that isn't actually included in the published package (verified --
// node_modules/@a2ui/react has no structural.css anywhere despite the
// exports map claiming one). Not importing it; a2ui-theme.css defines the
// --a2ui-* custom properties the renderer's inline styles read from, which
// is the actual supported theming path.

type ChatMessage = { role: "user" | "assistant"; content: string };

// The model reliably emits **bold** and "- " bullets; the bubble used to
// render `{content}` as a plain string, so users read `- **Budget max:**
// $30,000` verbatim. Built as React nodes rather than by setting innerHTML:
// this text is model output and, one prompt-injection away, third-party
// listing prose, so it must never be parsed as markup.
function renderMarkdown(text: string) {
  return text.split("\n").map((line, i) => {
    const bullet = /^\s*[-*]\s+/.test(line);
    const body = bullet ? line.replace(/^\s*[-*]\s+/, "") : line;
    const parts = body.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, j) =>
      part.startsWith("**") && part.endsWith("**") && part.length > 4
        ? <strong key={j}>{part.slice(2, -2)}</strong>
        : <span key={j}>{part}</span>,
    );
    return (
      <span key={i} className={bullet ? "chat-line chat-line--bullet" : "chat-line"}>
        {parts}
      </span>
    );
  });
}

function getSessionId(): string {
  const key = "car-matchmaker-session-id";
  let id = localStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(key, id);
  }
  return id;
}

const WS_HOST = import.meta.env.VITE_AGENT_BACKEND_HOST ?? window.location.hostname;
const WS_PORT = import.meta.env.VITE_AGENT_BACKEND_PORT ?? "8000";

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [typing, setTyping] = useState(false);
  // The booking MCP App, when the backend has one open for us. One at a
  // time by design: an App is bound to a phase, and the phase is singular.
  const [mcpApp, setMcpApp] = useState<McpAppEnvelope | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  // Tool calls the App has made and the backend has not answered yet.
  // Keyed by call_id because replies arrive on the shared socket, out of
  // band and potentially out of order.
  const pendingCalls = useRef(
    new Map<string, { resolve: (result: Record<string, unknown>) => void; reject: (err: Error) => void }>(),
  );
  // MessageProcessor's 2nd constructor argument is a global ActionListener:
  // it receives every action dispatched by any component on any surface
  // (e.g. a catalogue card's "Choose this one" Button). Relayed to the
  // backend as {"type":"action"}, where it is applied in code.
  //
  // wsRef rather than a state value on purpose: this listener is created
  // once with the processor and would otherwise close over the socket as it
  // was on first render, which is null.
  const [processor] = useState(
    () =>
      new MessageProcessor([basicCatalog], (clientAction) => {
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        // Mind the key. The component *declares* its handler under `event`
        // (server -> client), but what the listener receives is the
        // client -> server envelope, which nests it under `action` and adds
        // surfaceId/sourceComponentId/timestamp. Reading `.event` here
        // silently matched nothing and the button did nothing at all --
        // no error, no request. Verified against the installed
        // A2uiClientActionSchema.
        const payload =
          (clientAction as { action?: { name?: string; context?: Record<string, unknown> } })
            .action ?? (clientAction as { name?: string; context?: Record<string, unknown> });
        if (!payload?.name) return;

        ws.send(JSON.stringify({
          type: "action",
          name: payload.name,
          context: payload.context ?? {},
        }));
      }),
  );
  const [rawSurfaces, setSurfaces] = useState(() =>
    Array.from(processor.model.surfacesMap.values()),
  );
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerBadge, setDrawerBadge] = useState(0);

  useEffect(() => {
    const sync = () => setSurfaces(Array.from(processor.model.surfacesMap.values()));
    const createdSub = processor.onSurfaceCreated(sync);
    const deletedSub = processor.onSurfaceDeleted(sync);
    return () => {
      createdSub.unsubscribe();
      deletedSub.unsubscribe();
    };
  }, [processor]);

  // Cancel handler: clears the booking/checkout card and sends a
  // cancel_selection action so the backend resets the phase.
  const handleCancelMcpApp = useCallback(() => {
    setMcpApp(null);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "action", name: "cancel_selection", context: {} }));
    }
  }, []);

  useEffect(() => {
    let retries = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let unmounted = false;

    function connect() {
      const ws = new WebSocket(`ws://${WS_HOST}:${WS_PORT}/ws/${getSessionId()}`);
      wsRef.current = ws;

      ws.onopen = () => {
        retries = 0;
        setConnected(true);
      };
      ws.onclose = () => {
        setConnected(false);
        // Reject every pending tool call so the MCP App does not sit on
        // "Submitting…" forever after a disconnect.
        for (const { reject } of pendingCalls.current.values()) {
          reject(new Error("WebSocket closed"));
        }
        pendingCalls.current.clear();
        // Auto-reconnect with exponential backoff (1s, 2s, 4s, … cap 30s).
        if (!unmounted) {
          const delay = Math.min(1000 * 2 ** retries, 30_000);
          retries += 1;
          timer = setTimeout(connect, delay);
        }
      };
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "chat") {
          setTyping(false);
          setMessages((prev) => [...prev, { role: data.role, content: data.content }]);
        } else if (data.type === "typing") {
          setTyping(!!data.typing);
        } else if (data.type === "a2ui") {
          processor.processMessages(data.messages);
        } else if (data.type === "error") {
          // The backend now clears typing before every error, but the client
          // clears it here too: an error bubble under three bouncing dots
          // says "failed" and "still working" at the same time, and this is
          // the one place that is cheap to make unconditional.
          setTyping(false);
          setMessages((prev) => [...prev, { role: "assistant", content: `⚠️ ${data.message}` }]);
        } else if (data.type === "mcp_app") {
          setMcpApp(data as McpAppEnvelope);
          // The drawer auto-opens when results arrive and renders a
          // full-viewport backdrop above the chat column, so the booking
          // form landed *underneath* it: the user's first click on the form
          // was spent dismissing the drawer instead. The form is the task
          // now, so the results panel steps aside for it.
          setDrawerOpen(false);
        } else if (data.type === "app_tool_result") {
          const pending = pendingCalls.current.get(data.call_id);
          if (pending) {
            pendingCalls.current.delete(data.call_id);
            pending.resolve(data.result?.structuredContent ?? {});
          }
        }
      };
    }

    connect();
    return () => {
      unmounted = true;
      if (timer) clearTimeout(timer);
      wsRef.current?.close();
    };
  }, [processor]);

  // Keep the newest message in view; a research turn appends several.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Handed to the MCP App host, which gives it to `AppBridge.oncalltool`.
  // The App awaits this, so every path has to settle: a rejected promise
  // surfaces in the form as an error the user can act on, whereas a promise
  // that never resolves leaves it stuck on "Submitting…" forever.
  const callServerTool = (name: string, args: Record<string, unknown>) =>
    new Promise<Record<string, unknown>>((resolve, reject) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        reject(new Error("not connected"));
        return;
      }
      const callId = crypto.randomUUID();
      pendingCalls.current.set(callId, { resolve, reject });
      ws.send(JSON.stringify({
        type: "app_tool_call", call_id: callId, name, arguments: args,
      }));
    });

  const sendText = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: "chat", content: trimmed }));
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setInput("");
  };

  // The chips used to call `setInput` only: the empty state says "pick a
  // suggestion", nothing was sent, and focus stayed on the chip -- so
  // pressing Enter re-fired the chip rather than sending, and a
  // keyboard-only user could not start a conversation from them at all.
  const send = () => sendText(input);

  // Start over. CONFIRMED binds no tools and no transition leaves it, and
  // the session id is permanent in localStorage, so after a successful
  // checkout the only way to run the flow again was to clear site data.
  const startOver = () => {
    localStorage.removeItem("car-matchmaker-session-id");
    window.location.reload();
  };

  const surfaces = rawSurfaces.filter((s) => s.id !== "interview-progress");

  // Auto-open drawer when the backend sends new/updated surfaces.
  // The processor fires onSurfaceCreated for new surfaces and
  // onSurfaceDeleted for removed ones — but catalogue updates are
  // in-place (no event).  We track a fingerprint of all surface IDs +
  // component counts so any change (new surface, removed surface, or
  // updated content) triggers auto-open.
  const fingerprint = surfaces
    .map((s) => `${s.id}:${(s as any).components?.length ?? 0}`)
    .join("|");
  const prevFingerprint = useRef(fingerprint);
  useEffect(() => {
    if (fingerprint !== prevFingerprint.current && fingerprint) {
      if (drawerOpen) {
        // Drawer is already open — content updates silently.
      } else {
        // Drawer closed — show badge so the user knows results changed.
        setDrawerBadge((b) => b + 1);
      }
      setDrawerOpen(true);
    }
    prevFingerprint.current = fingerprint;
  }, [fingerprint, drawerOpen]);

  // Clear badge when drawer opens.
  useEffect(() => {
    if (drawerOpen) setDrawerBadge(0);
  }, [drawerOpen]);

  // Escape key closes the drawer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && drawerOpen) setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  return (
    <div className="app">
      <div className="chat">
        <div className="chat-header">
          <h1 className="chat-title">AI Car Matchmaker</h1>
          <div className="chat-header-right">
            <span
              className="chat-status"
              data-connected={connected}
              data-testid="connection-status"
            >
              {connected ? "connected" : "offline"}
            </span>
            {messages.length > 0 && (
              <button className="chat-restart" onClick={startOver} data-testid="start-over">
                Start over
              </button>
            )}
          </div>
        </div>

        <div className="chat-log" data-testid="chat-log" ref={logRef}>
          {messages.length === 0 && (
            <div className="chat-empty">
              <p className="chat-empty-text">
                Tell me what you're looking for, or pick a suggestion:
              </p>
              <div className="chat-chips">
                {[
                  "I need a family SUV under $25k",
                  "Show me budget sedans",
                  "I want a hatchback for road trips",
                  "Find me a truck for work",
                ].map((chip) => (
                  <button
                    key={chip}
                    className="chat-chip"
                    onClick={() => sendText(chip)}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className="chat-row" data-role={m.role}>
              <span className="chat-bubble">
                {m.role === "assistant" ? renderMarkdown(m.content) : m.content}
              </span>
            </div>
          ))}
          {typing && (
            <div className="chat-row" data-role="assistant">
              <span className="chat-bubble typing-indicator">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </span>
            </div>
          )}
        </div>

        {/* In the chat column, not the surfaces panel (decided 2026-08-08):
            requirement #3 is that booking happens *inside the conversation*,
            and a form in a side panel reads as leaving it. It sits below the
            log and above the composer so the user can still talk while the
            form is open. */}
        {mcpApp && (
          <McpAppFrame
            key={JSON.stringify(mcpApp.toolInput)}
            envelope={mcpApp}
            onCallTool={callServerTool}
            onCancel={handleCancelMcpApp}
          />
        )}

        <div className="composer">
          <input
            data-testid="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Tell me what car you're looking for..."
          />
          <button data-testid="chat-send" onClick={send} disabled={!connected} aria-label="Send message">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="12" x2="19" y2="12" />
              <polyline points="12 5 19 12 12 19" />
            </svg>
          </button>
        </div>
      </div>

      {/* Slide-out drawer toggle button */}
      {surfaces.length > 0 && (
        <button
          className="drawer-toggle"
          onClick={() => setDrawerOpen((o) => !o)}
          aria-label={drawerOpen ? "Close panel" : "Open panel"}
        >
          {drawerOpen ? "\u2715" : "\u2630"}
          {!drawerOpen && drawerBadge > 0 && (
            <span className="drawer-badge">{drawerBadge}</span>
          )}
        </button>
      )}

      {/* Slide-out drawer */}
      {/* `inert` when closed: the drawer is hidden with a transform only,
          so without this its "Choose this one" buttons stay focusable and
          screen-reader-visible while sitting off-screen at x=837. */}
      <div className={`drawer ${drawerOpen ? "drawer--open" : ""}`} inert={!drawerOpen}>
        <div className="drawer-header">
          <h2 className="drawer-title">Results</h2>
          <button
            className="drawer-close"
            onClick={() => setDrawerOpen(false)}
            aria-label="Close panel"
          >
            {"\u2715"}
          </button>
        </div>
        <div className="drawer-body" data-testid="a2ui-panel">
          {surfaces.map((surface) => (
            <div key={surface.id} className="a2ui-surface" data-surface-id={surface.id}>
              <A2uiSurface surface={surface} />
            </div>
          ))}
          {surfaces.length === 0 && (
            <p className="surfaces-empty">Results will appear here.</p>
          )}
        </div>
      </div>
      {drawerOpen && <div className="drawer-backdrop" onClick={() => setDrawerOpen(false)} />}
    </div>
  );
}
