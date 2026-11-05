import { useEffect, useRef, useState } from 'react'
import { Camera, MousePointer2, ParkingSquare, WifiOff } from 'lucide-react'
import { ParkingTwin } from '../twin/ParkingTwin.js'
import { useParking } from '../store/ParkingContext.jsx'
import { ConnectionPill } from '../components/Layout.jsx'

const GATE_STYLE = {
  OPEN: 'text-neon-emerald border-neon-emerald/40 bg-neon-emerald/10',
  OPENING: 'text-neon-emerald border-neon-emerald/40 bg-neon-emerald/10',
  CLOSING: 'text-amber-300 border-amber-300/40 bg-amber-300/10',
  CLOSED: 'text-slate-300 border-white/15 bg-white/5',
}

function GateChip({ label, state }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="label">{label}</span>
      <span className={`inline-flex w-fit items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[11px] font-semibold ${GATE_STYLE[state]}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${state === 'CLOSED' ? 'bg-neon-coral' : 'bg-neon-emerald'}`} />
        {state}
      </span>
    </div>
  )
}

const LOG_COLOR = {
  entry_ocr: 'text-neon-cyan', slot_occupied: 'text-neon-coral', exit_ocr: 'text-amber-300',
  payment_confirmed: 'text-neon-emerald', slot_released: 'text-slate-300', sync: 'text-slate-400',
}

export default function TwinPage() {
  const { conn, subscribe, getSceneState, log, crm } = useParking()
  const hostRef = useRef(null)
  const twinRef = useRef(null)
  const [gates, setGates] = useState({ entry: 'CLOSED', exit: 'CLOSED' })
  const [stats, setStats] = useState({ free: 4, total: 4, slots: Array.from({ length: 4 }, () => ({ status: 'FREE', plate: null })) })
  const [glError, setGlError] = useState(null)

  useEffect(() => {
    let twin
    try {
      twin = new ParkingTwin(hostRef.current, { onGateChange: setGates, onStats: setStats })
    } catch (err) {
      console.error(err)
      setGlError(err.message || 'WebGL is not available')
      return undefined
    }
    twinRef.current = twin
    twin.applyState(getSceneState()) // rebuild from the event-driven mirror (empty on a fresh start)

    const unsub = subscribe((ev) => {
      if (ev.type === 'STATE') twin.applyState(ev.state)
      else if (ev.type === 'EVENT') twin.handleEvent(ev.msg, ev.slotIndex)
    })
    return () => {
      unsub()
      twin.dispose()
      twinRef.current = null
    }
  }, [subscribe, getSceneState])

  useEffect(() => {
    twinRef.current && twinRef.current.setCurrency(crm.currency)
  }, [crm.currency])

  return (
    <div className="absolute inset-0 overflow-hidden">
      <div ref={hostRef} className="absolute inset-0" />

      {glError && (
        <div className="absolute inset-0 flex items-center justify-center p-6">
          <div className="glass-strong max-w-md rounded-2xl p-6 text-center">
            <div className="font-display text-lg text-neon-coral">WebGL unavailable</div>
            <p className="mt-2 text-sm text-slate-300">{glError}. Enable hardware acceleration or try another browser. The CRM page still works.</p>
          </div>
        </div>
      )}

      {/* top status bar */}
      <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center px-3">
        <div className="glass-strong pointer-events-auto grid w-full max-w-4xl grid-cols-2 items-center gap-x-6 gap-y-3 rounded-2xl px-5 py-3 sm:grid-cols-[auto_1fr_1fr_auto]">
          <div className="flex items-center gap-3">
            <ParkingSquare className="text-neon-cyan" size={22} />
            <div>
              <div className="label">Available slots</div>
              <div className="font-display text-2xl font-bold leading-none">
                <span className={stats.free > 0 ? 'text-neon-emerald' : 'text-neon-coral'}>{stats.free}</span>
                <span className="text-slate-500">/{stats.total}</span>
              </div>
            </div>
          </div>
          <GateChip label="Entrance gate" state={gates.entry} />
          <GateChip label="Exit gate" state={gates.exit} />
          <div className="col-span-2 flex flex-col gap-1 sm:col-span-1 sm:items-end">
            <span className="label">WebSocket</span>
            <ConnectionPill conn={conn} />
          </div>
        </div>
      </div>

      {conn !== 'online' && (
        <div className="pointer-events-none absolute inset-x-0 top-28 flex justify-center px-3 sm:top-24">
          <div className="glass inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs text-slate-300">
            <WifiOff size={13} className="text-neon-coral" />
            {conn === 'connecting' ? 'Connecting to ws://localhost:8000/ws/parking …' : 'Backend offline — retrying. The scene only reacts to live events.'}
          </div>
        </div>
      )}

      {/* bottom-left: read-only slot list + event stream */}
      <div className="pointer-events-none absolute bottom-4 left-4 hidden w-72 flex-col gap-3 lg:flex">
        <div className="glass pointer-events-auto rounded-2xl p-3">
          <div className="label mb-2">Slots</div>
          <div className="grid grid-cols-2 gap-2">
            {stats.slots.map((s, i) => {
              const occ = s.status === 'OCCUPIED'
              return (
                <div key={i} className={`rounded-lg border px-2.5 py-1.5 ${occ ? 'border-neon-coral/40 bg-neon-coral/10' : 'border-neon-emerald/30 bg-neon-emerald/5'}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-display text-xs font-bold">#{i + 1}</span>
                    <span className={`h-2 w-2 rounded-full ${occ ? 'bg-neon-coral shadow-glow-coral' : 'bg-neon-emerald shadow-glow-emerald'}`} />
                  </div>
                  <div className="mt-0.5 truncate font-mono text-[11px] text-slate-300">{occ ? s.plate : 'FREE'}</div>
                </div>
              )
            })}
          </div>
        </div>
        <div className="glass pointer-events-auto max-h-44 overflow-y-auto rounded-2xl p-3">
          <div className="label mb-1.5">Event stream</div>
          {log.length === 0 && <div className="font-mono text-[11px] text-slate-500">waiting for events…</div>}
          {log.slice(0, 8).map((l) => (
            <div key={l.id} className={`truncate font-mono text-[11px] ${LOG_COLOR[l.kind] || 'text-slate-300'}`}>
              <span className="text-slate-600">{l.at.toLocaleTimeString('en-GB')}</span> {l.text}
            </div>
          ))}
        </div>
      </div>

      <div className="absolute bottom-4 right-4 flex flex-col items-end gap-2">
        <button
          onClick={() => twinRef.current && twinRef.current.resetCamera()}
          className="glass-strong pointer-events-auto inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-[11px] text-slate-300 transition hover:text-neon-cyan"
        >
          <Camera size={13} /> Reset camera
        </button>
        <div className="pointer-events-none hidden items-center gap-2 text-[11px] text-slate-500 xl:flex">
          <MousePointer2 size={12} /> drag to orbit · scroll to zoom · right-drag to pan
        </div>
      </div>
    </div>
  )
}
