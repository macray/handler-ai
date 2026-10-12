// Contract C.1 in the browser: an agent's or a session's ACP WebSocket as an ACP SDK `Stream`.
//   subprotocols: "acp.v1" + "bearer.<token>" (browsers cannot set an Authorization header)
//   framing:      one JSON-RPC message per text frame
import type { AnyMessage, Stream } from "@agentclientprotocol/sdk";
import type { Closed, OpenTransport } from "@handler/acp-view/lib/connection.svelte";

export type { Closed };

export const ACP_SUBPROTOCOL = "acp.v1";

/** The transport of an `AcpConnection` to one of handlerd's ACP endpoints. */
export function websocketTransport(url: string, token: string): OpenTransport {
  return async (onClose) => {
    const ws = await openWebSocket(url, token);
    return { stream: websocketStream(ws, onClose), close: () => ws.close(1000, "closed by user") };
  };
}

export function openWebSocket(url: string, token: string, Ctor: typeof WebSocket = WebSocket): Promise<WebSocket> {
  return new Promise((resolve, reject) => {
    const ws = new Ctor(url, [ACP_SUBPROTOCOL, `bearer.${token}`]);
    ws.addEventListener("open", () => resolve(ws), { once: true });
    ws.addEventListener("close", (e) => reject(new Error(`connection refused (${e.code}) ${e.reason}`)), {
      once: true,
    });
  });
}

/** The SDK reads/writes message objects; we (de)serialize one message per frame. */
export function websocketStream(ws: WebSocket, onClose: (closed: Closed) => void): Stream {
  const readable = new ReadableStream<AnyMessage>({
    start(controller) {
      ws.addEventListener("message", (event) => {
        if (typeof event.data !== "string") return;
        for (const line of event.data.split("\n")) {
          if (line.trim()) controller.enqueue(JSON.parse(line) as AnyMessage);
        }
      });
      ws.addEventListener("close", (event) => {
        onClose({ code: event.code, reason: event.reason });
        try {
          controller.close();
        } catch {
          /* already closed */
        }
      });
    },
  });
  const writable = new WritableStream<AnyMessage>({
    write(message) {
      ws.send(JSON.stringify(message));
    },
    close() {
      ws.close();
    },
  });
  return { readable, writable };
}
