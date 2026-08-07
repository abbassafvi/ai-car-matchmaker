import { useEffect, useRef, useState } from "react";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { A2uiSurface, basicCatalog } from "@a2ui/react/v0_9";
// Note: @a2ui/react@0.10.2's "./styles/structural.css" export points at a
// file that isn't actually included in the published package (verified --
// node_modules/@a2ui/react has no structural.css anywhere despite the
// exports map claiming one). Not importing it; components render unstyled
// but functional without it.

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
  const [processor] = useState(() => new MessageProcessor([basicCatalog]));
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

  const send = () => {
    if (!input.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: "chat", content: input }));
    setMessages((prev) => [...prev, { role: "user", content: input }]);
    setInput("");
  };

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "sans-serif" }}>
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          padding: 16,
          borderRight: "1px solid #ddd",
        }}
      >
        <h2>
          AI Car Matchmaker <span data-testid="connection-status">{connected ? "🟢" : "🔴"}</span>
        </h2>
        <div style={{ flex: 1, overflowY: "auto" }} data-testid="chat-log">
          {messages.map((m, i) => (
            <div key={i} style={{ margin: "8px 0", textAlign: m.role === "user" ? "right" : "left" }}>
              <span
                style={{
                  display: "inline-block",
                  padding: "8px 12px",
                  borderRadius: 8,
                  background: m.role === "user" ? "#0366d6" : "#eee",
                  color: m.role === "user" ? "white" : "black",
                  maxWidth: "80%",
                }}
              >
                {m.content}
              </span>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            data-testid="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Tell me what car you're looking for..."
            style={{ flex: 1, padding: 8 }}
          />
          <button data-testid="chat-send" onClick={send}>
            Send
          </button>
        </div>
      </div>
      <div style={{ flex: 1, padding: 16, overflowY: "auto" }} data-testid="a2ui-panel">
        <h2>Progress</h2>
        {surfaces.map((surface) => (
          <A2uiSurface key={surface.id} surface={surface} />
        ))}
      </div>
    </div>
  );
}
