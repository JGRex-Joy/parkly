import { useEffect, useRef, useState, useCallback } from "react";

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export function useWebSocket<TEvent>(url: string | null) {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [lastEvent, setLastEvent] = useState<TEvent | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retryDelayRef = useRef(500);
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedByUsRef = useRef(false);

  const connect = useCallback(() => {
    if (!url) return;

    setStatus("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      retryDelayRef.current = 500; 
      setStatus("connected");
    };

    ws.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data) as TEvent;
        setLastEvent(parsed);
      } catch (e) {
        console.warn("Не удалось распарсить сообщение WS:", msg.data);
      }
    };

    ws.onerror = () => {
    };

    ws.onclose = () => {
      setStatus("disconnected");
      if (closedByUsRef.current) return;

      retryTimeoutRef.current = setTimeout(() => {
        retryDelayRef.current = Math.min(retryDelayRef.current * 1.5, 5000);
        connect();
      }, retryDelayRef.current);
    };
  }, [url]);

  useEffect(() => {
    closedByUsRef.current = false;
    connect();

    return () => {
      closedByUsRef.current = true;
      if (retryTimeoutRef.current) clearTimeout(retryTimeoutRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { status, lastEvent };
}
