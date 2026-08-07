// Live-trace WebSocket. Subscribes to a session's ReAct step stream (contracts/
// live-trace-ws.md). Auto-reconnects while the session is open. Events are DATA:
// panels render them inert (text bindings), never as HTML (research R7).

export interface TraceEvent {
  type: string;
  source_type?: string;
  [k: string]: unknown;
}

export function connectTrace(
  sessionId: string,
  onEvent: (e: TraceEvent) => void,
): { close: () => void } {
  let closed = false;
  let sock: WebSocket | null = null;

  const open = () => {
    if (closed) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    sock = new WebSocket(`${proto}://${location.host}/ws/session/${sessionId}`);
    sock.onmessage = (m) => {
      try {
        onEvent(JSON.parse(m.data) as TraceEvent);
      } catch {
        /* ignore malformed frame */
      }
    };
    sock.onclose = () => {
      if (!closed) setTimeout(open, 1000); // reconnect while the session lives
    };
  };
  open();

  return {
    close() {
      closed = true;
      sock?.close();
    },
  };
}
