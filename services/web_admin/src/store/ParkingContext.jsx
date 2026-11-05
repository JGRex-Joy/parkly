import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useParkingSocket } from '../hooks/useParkingSocket.js'
import { fetchConfig, fetchSessions } from '../lib/api.js'
import { currencySymbol, parseUtc } from '../lib/format.js'
import { emptyMirror, fromSnapshot, reduce, slotIndexOf, toSceneState } from '../lib/stateMirror.js'

const Ctx = createContext(null)
export const useParking = () => useContext(Ctx)

const PIPELINE_EVENTS = new Set(['ENTRY_OCR', 'SLOT_OCCUPIED', 'EXIT_OCR', 'PAYMENT_CONFIRMED', 'SLOT_RELEASED'])

function uiStatus(r) {
  switch (r.status) {
    case 'ACTIVE': return r.exit_time ? 'Awaiting payment' : 'Active'
    case 'COMPLETED': return 'Completed'
    default: return 'Exception'
  }
}

export function ParkingProvider({ children }) {
  const mirror = useRef(emptyMirror())
  const listeners = useRef(new Set())
  const refreshTimer = useRef(null)
  const refreshRef = useRef(() => {})
  const [live, setLive] = useState(() => ({ slots: mirror.current.slots }))
  const [log, setLog] = useState([])
  const [toasts, setToasts] = useState([])
  const [crm, setCrm] = useState({ rows: [], status: 'idle', error: null, currency: '₸' })

  const subscribe = useCallback((fn) => {
    listeners.current.add(fn)
    return () => listeners.current.delete(fn)
  }, [])
  const emit = useCallback((e) => listeners.current.forEach((fn) => fn(e)), [])
  const getSceneState = useCallback(() => toSceneState(mirror.current), [])

  const pushLog = useCallback((kind, text) => {
    setLog((l) => [{ id: Math.random().toString(36).slice(2), at: new Date(), kind, text }, ...l].slice(0, 40))
  }, [])

  const toast = useCallback((text, tone = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t, { id, text, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500)
  }, [])

  // ---------------------------------------------------------------- CRM history (real DB rows)
  const refreshSessions = useCallback(async () => {
    try {
      const data = await fetchSessions()
      const ids = mirror.current.slotIds
      const rows = data.map((r) => ({
        id: r.id,
        plate: r.plate_number,
        rawStatus: r.status,
        status: uiStatus(r),
        staff: false,
        entryAt: parseUtc(r.entry_time),
        exitAt: parseUtc(r.exit_time),
        paidAt: parseUtc(r.paid_time),
        durationSec: r.duration_seconds,
        fee: r.fee,
        slotIndex: r.slot_id == null ? -1 : ids.indexOf(r.slot_id),
      }))
      setCrm((c) => ({ ...c, rows, status: 'ready', error: null }))
    } catch (err) {
      setCrm((c) => ({ ...c, status: 'error', error: err.message }))
    }
  }, [])
  refreshRef.current = refreshSessions

  const scheduleRefresh = useCallback(() => {
    clearTimeout(refreshTimer.current)
    refreshTimer.current = setTimeout(() => refreshRef.current(), 350)
  }, [])

  // ---------------------------------------------------------------- WebSocket messages
  const handleMessage = useCallback((msg) => {
    if (msg.event === 'INITIAL_STATE') {
      mirror.current = fromSnapshot(msg)
      setLive({ slots: [...mirror.current.slots] })
      emit({ type: 'STATE', state: toSceneState(mirror.current) })
      pushLog('sync', `INITIAL_STATE · ${msg.free_slots}/${msg.total_slots} free`)
      scheduleRefresh()
      return
    }
    if (!PIPELINE_EVENTS.has(msg.event)) return
    const slotIndex = slotIndexOf(mirror.current, msg.slot_id)
    const before = mirror.current
    // transient-noise filter: drop events that the sticky mirror would not act on
    if (msg.event === 'SLOT_RELEASED' && slotIndex >= 0 && before.slots[slotIndex].plate) return
    if (msg.event === 'SLOT_OCCUPIED' && slotIndex >= 0 && before.slots[slotIndex].plate === msg.plate &&
        before.sessions[msg.plate]?.phase === 'PARKED') return
    reduce(mirror.current, msg)
    setLive({ slots: [...mirror.current.slots] })
    emit({ type: 'EVENT', msg, slotIndex })
    const detail = [msg.plate, slotIndex >= 0 ? `slot ${slotIndex + 1}` : null].filter(Boolean).join(' · ')
    pushLog(msg.event.toLowerCase(), `${msg.event}${detail ? ` · ${detail}` : ''}`)
    scheduleRefresh()
  }, [emit, pushLog, scheduleRefresh])

  const conn = useParkingSocket(handleMessage)

  useEffect(() => {
    fetchConfig()
      .then((c) => setCrm((s) => ({ ...s, currency: currencySymbol(c.currency) })))
      .catch(() => {})
  }, [conn === 'online'])

  const prevConn = useRef(conn)
  useEffect(() => {
    if (prevConn.current === conn) return
    if (conn === 'online') toast('Connected to /ws/parking', 'ok')
    if (conn === 'offline' && prevConn.current === 'online') toast('WebSocket connection lost — reconnecting…', 'warn')
    prevConn.current = conn
  }, [conn, toast])

  useEffect(() => () => clearTimeout(refreshTimer.current), [])

  const value = useMemo(
    () => ({ conn, live, log, toasts, crm, subscribe, getSceneState, refreshSessions, slotIds: mirror.current.slotIds }),
    [conn, live, log, toasts, crm, subscribe, getSceneState, refreshSessions],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
