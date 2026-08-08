import { useEffect, useRef, useState } from "react";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { A2uiSurface, basicCatalog } from "@a2ui/react/v0_9";
import "./app.css";
import "./a2ui-theme.css";
// Note: @a2ui/react@0.10.2's "./styles/structural.css" export points at a
// file that isn't actually included in the published package (verified --
// node_modules/@a2ui/react has no structural.css anywhere despite the
// exports map claiming one). Not importing it; a2ui-theme.css defines the
// --a2ui-* custom properties the renderer's inline styles read from, which
// is the actual supported theming path.

type ChatMessage = { role: "user" | "assistant"; content: string };

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
  const wsRef = useRef<WebSocket | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
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
  const [surfaces, setSurfaces] = useState(() =>
    Array.from(processor.model.surfacesMap.values()),
  );

  useEffect(() => {
    const sync = () => setSurfaces(Array.from(processor.model.surfacesMap.values()));
    const createdSub = processor.onSurfaceCreated(sync);
    const deletedSub = processor.onSurfaceDeleted(sync);
    return () => {
      createdSub.unsubscribe();
      deletedSub.unsubscribe();
    };
  }, [processor]);

  useEffect(() => {
    const ws = new WebSocket(`ws://${WS_HOST}:${WS_PORT}/ws/${getSessionId()}`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "chat") {
        setMessages((prev) => [...prev, { role: data.role, content: data.content }]);
      } else if (data.type === "a2ui") {
        processor.processMessages(data.messages);
      } else if (data.type === "error") {
        setMessages((prev) => [...prev, { role: "assistant", content: `⚠️ ${data.message}` }]);
      }
    };

    return () => ws.close();
  }, [processor]);

  // Keep the newest message in view; a research turn appends several.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages]);

  const send = () => {
    if (!input.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: "chat", content: input }));
    setMessages((prev) => [...prev, { role: "user", content: input }]);
    setInput("");
  };

  return (
    <div className="app">
      <div className="chat">
        <div className="chat-header">
          <h1 className="chat-title">AI Car Matchmaker</h1>
          <span
            className="chat-status"
            data-connected={connected}
            data-testid="connection-status"
          >
            {connected ? "connected" : "offline"}
          </span>
        </div>

        <div className="chat-log" data-testid="chat-log" ref={logRef}>
          {messages.length === 0 && (
            <p className="chat-empty">
              Tell me what you're after — what you'll use it for, the kind of car,
              your budget, whether you want to buy or rent, and when you need it.
            </p>
          )}
          {messages.map((m, i) => (
            <div key={i} className="chat-row" data-role={m.role}>
              <span className="chat-bubble">{m.content}</span>
            </div>
          ))}
        </div>

        <div className="composer">
          <input
            data-testid="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Tell me what car you're looking for..."
          />
          <button data-testid="chat-send" onClick={send} disabled={!connected}>
            Send
          </button>
        </div>
      </div>

      <div className="surfaces" data-testid="a2ui-panel">
        {/* Every surface the agent creates renders here automatically -- the
            backend can add surfaces (interview progress, reasoning steps,
            catalogue) without the frontend knowing their names. */}
        {surfaces.length === 0 && (
          <p className="surfaces-empty">The agent's progress will appear here.</p>
        )}
        {surfaces.map((surface) => (
          <div key={surface.id} className="a2ui-surface" data-surface-id={surface.id}>
            <A2uiSurface surface={surface} />
          </div>
        ))}
      </div>
    </div>
  );
}
