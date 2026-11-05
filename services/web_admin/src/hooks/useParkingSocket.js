import { useEffect, useRef, useState } from 'react'
import { WS_URL } from '../lib/api.js'

export function useParkingSocket(onMessage) {
  const [status, setStatus] = useState('connecting')
  const handlerRef = useRef(onMessage)
  handlerRef.current = onMessage

  useEffect(() => {
    let ws = null
    let retry = 0
    let timer = null
    let heartbeat = null
    let stopped = false

    const connect = () => {
      if (stopped) return
      setStatus((s) => (s === 'online' ? s : 'connecting'))
      try {
        ws = new WebSocket(WS_URL)
      } catch {
        schedule()
        return
      }
      ws.onopen = () => {
        retry = 0
        setStatus('online')
        heartbeat = setInterval(() => ws.readyState === 1 && ws.send('ping'), 25000)
      }
      ws.onmessage = (ev) => {
        try { handlerRef.current(JSON.parse(ev.data)) } catch (e) { console.warn('bad WS payload', e) }
      }
      ws.onclose = () => {
        clearInterval(heartbeat)
        if (stopped) return
        setStatus('offline')
        schedule()
      }
      ws.onerror = () => ws && ws.close()
    }

    const schedule = () => {
      const delay = Math.min(1500 * 2 ** retry, 15000)
      retry += 1
      timer = setTimeout(connect, delay)
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      clearInterval(heartbeat)
      if (ws) { ws.onclose = null; ws.close() }
    }
  }, [])

  return status
}
