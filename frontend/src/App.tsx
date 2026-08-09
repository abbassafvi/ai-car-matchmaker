import { useCallback, useEffect, useRef, useState } from "react";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { A2uiSurface, basicCatalog } from "@a2ui/react/v0_9";
import McpAppFrame from "./mcp-app-host/McpAppFrame";
import type { McpAppEnvelope } from "./mcp-app-host/types";
import "./app.css";
import "./a2ui-theme.css";

type ChatMessage = { role: "user" | "assistant"; content: string };

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

// Interview slot labels for the brief chips.
const SLOT_LABELS: Record<string, string> = {
  use_case: "Use",
  category: "Type",
  budget_max: "Budget",
  transaction_type: "Mode",
  target_date: "When",
};

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(true);
  const [typing, setTyping] = useState(false);
  const [mcpApp, setMcpApp] = useState<McpAppEnvelope | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const lastUserMsg = useRef("");
  const pendingCalls = useRef(
    new Map<string, { resolve: (result: Record<string, unknown>) => void; reject: (err: Error) => void }>(),
  );

  const [processor] = useState(
    () =>
      new MessageProcessor([basicCatalog], (clientAction) => {
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
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

  useEffect(() => {
    const sync = () => setSurfaces(Array.from(processor.model.surfacesMap.values()));
    const createdSub = processor.onSurfaceCreated(sync);
    const deletedSub = processor.onSurfaceDeleted(sync);
    return () => {
      createdSub.unsubscribe();
      deletedSub.unsubscribe();
    };
  }, [processor]);

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
        setRetryCount(0);
      };
      ws.onclose = () => {
        setConnected(false);
        for (const { reject } of pendingCalls.current.values()) {
          reject(new Error("WebSocket closed"));
        }
        pendingCalls.current.clear();
        if (!unmounted) {
          const delay = Math.min(1000 * 2 ** retries, 30_000);
          retries += 1;
          setRetryCount(retries);
          timer = setTimeout(connect, delay);
        }
      };
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "chat") {
          setTyping(false);
          setLastError(null);
          setMessages((prev) => [...prev, { role: data.role, content: data.content }]);
        } else if (data.type === "typing") {
          setTyping(!!data.typing);
        } else if (data.type === "a2ui") {
          processor.processMessages(data.messages);
        } else if (data.type === "error") {
          setTyping(false);
          setLastError(data.message);
        } else if (data.type === "mcp_app") {
          setMcpApp(data as McpAppEnvelope);
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

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, typing]);

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
    lastUserMsg.current = trimmed;
    wsRef.current.send(JSON.stringify({ type: "chat", content: trimmed }));
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setInput("");
    setLastError(null);
  };

  const send = () => sendText(input);

  const retryLast = () => {
    if (lastUserMsg.current) sendText(lastUserMsg.current);
  };

  const startOver = () => {
    localStorage.removeItem("car-matchmaker-session-id");
    window.location.reload();
  };

  // Extract interview brief from the interview-progress surface.
  const interviewSurface = rawSurfaces.find((s) => s.id === "interview-progress");
  const interviewBrief: Array<{ slot: string; label: string; value: string }> = [];
  if (interviewSurface) {
    // The surface components contain CheckBox items with label/value/filled.
    const comps = (interviewSurface as any).components ?? [];
    for (const comp of comps) {
      const items = comp?.items ?? comp?.children ?? [];
      for (const item of items) {
        if (item?.label && item?.value) {
          const slot = Object.keys(SLOT_LABELS).find(
            (k) => item.label.toLowerCase().includes(k.replace("_", " "))
          ) ?? item.label;
          interviewBrief.push({
            slot,
            label: SLOT_LABELS[slot] ?? item.label,
            value: String(item.value),
          });
        }
      }
    }
  }

  // Surfaces to render in the right pane (exclude interview-progress).
  const surfaces = rawSurfaces.filter((s) => s.id !== "interview-progress");

  // Reasoning steps from the research-reasoning surface.
  const reasoningSurface = rawSurfaces.find((s) => s.id === "research-reasoning");
  const reasoningSteps: string[] = [];
  if (reasoningSurface) {
    const comps = (reasoningSurface as any).components ?? [];
    for (const comp of comps) {
      const text = comp?.text?.content ?? comp?.content ?? "";
      if (text) reasoningSteps.push(text);
    }
  }

  const hasResults = surfaces.length > 0;
  const isEmpty = messages.length === 0 && !hasResults;

  return (
    <div className="app">
      {/* Disconnect banner — only shows when actually disconnected */}
      {!connected && (
        <div className="disconnect-banner">
          {retryCount > 0
            ? `Reconnecting… (attempt ${retryCount})`
            : "Connection lost — reconnecting…"}
        </div>
      )}

      <div className="chat">
        <div className="chat-header">
          <h1 className="chat-title">AI Car Matchmaker</h1>
          {messages.length > 0 && (
            <button className="chat-restart" onClick={startOver} data-testid="start-over">
              Start over
            </button>
          )}
        </div>

        <div className="chat-log" data-testid="chat-log" ref={logRef}>
          {isEmpty && (
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

          {/* Resumed session: show brief instead of empty state */}
          {!isEmpty && messages.length === 0 && interviewBrief.length > 0 && (
            <div className="chat-resumed">
              <p className="chat-resumed-text">
                Picking up where you left off —{" "}
                {interviewBrief.map((s) => `${s.value}`).join(", ")}.
              </p>
            </div>
          )}

          {/* Reasoning trace — inline in chat */}
          {reasoningSteps.length > 0 && typing && (
            <div className="chat-reasoning">
              {reasoningSteps.map((step, i) => (
                <span key={i} className="reasoning-step">{step}</span>
              ))}
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className="chat-row" data-role={m.role}>
              {m.role === "user" ? (
                <span className="chat-bubble">{m.content}</span>
              ) : (
                <div className="chat-prose">{renderMarkdown(m.content)}</div>
              )}
            </div>
          ))}

          {typing && reasoningSteps.length === 0 && (
            <div className="chat-row" data-role="assistant">
              <span className="chat-bubble typing-indicator">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </span>
            </div>
          )}

          {/* Error + retry */}
          {lastError && !typing && (
            <div className="chat-error">
              <span className="chat-error-text">{lastError}</span>
              <button className="chat-retry" onClick={retryLast}>Try again</button>
            </div>
          )}
        </div>

        {mcpApp && (
          <McpAppFrame
            key={JSON.stringify(mcpApp.toolInput)}
            envelope={mcpApp}
            onCallTool={callServerTool}
            onCancel={handleCancelMcpApp}
          />
        )}

        {/* Interview brief chips — above composer */}
        {interviewBrief.length > 0 && (
          <div className="brief-chips">
            {interviewBrief.map((s) => (
              <button
                key={s.slot}
                className="brief-chip"
                onClick={() => setInput(`Actually, my ${s.label.toLowerCase()} is…`)}
              >
                <span className="brief-chip-label">{s.label}</span>
                <span className="brief-chip-value">{s.value}</span>
              </button>
            ))}
          </div>
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

      {/* Persistent right pane — surfaces stream in here directly */}
      <div className="surfaces" data-testid="a2ui-panel">
        {surfaces.map((surface) => (
          <div key={surface.id} className="a2ui-surface" data-surface-id={surface.id}>
            <A2uiSurface surface={surface} />
          </div>
        ))}
        {surfaces.length === 0 && (
          <div className="surfaces-empty">
            <p>Results will appear here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
