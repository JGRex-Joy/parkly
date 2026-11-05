import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { BarChart3, Box, CheckCircle2, AlertTriangle, Info, Radio, WifiOff, Loader2 } from 'lucide-react'
import { useParking } from '../store/ParkingContext.jsx'

export function ConnectionPill({ conn, exec = false }) {
  const map = {
    online: { Icon: Radio, text: 'LIVE', sub: '/ws/parking', cls: 'text-neon-emerald border-neon-emerald/40 bg-neon-emerald/10', dot: 'bg-neon-emerald', ex: 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10' },
    connecting: { Icon: Loader2, text: 'CONNECTING', sub: 'ws://…', cls: 'text-amber-300 border-amber-300/40 bg-amber-300/10', dot: 'bg-amber-300', ex: 'text-amber-300 border-amber-400/30 bg-amber-400/10' },
    offline: { Icon: WifiOff, text: 'OFFLINE', sub: 'reconnecting', cls: 'text-neon-coral border-neon-coral/40 bg-neon-coral/10', dot: 'bg-neon-coral', ex: 'text-red-300 border-red-500/30 bg-red-500/10' },
  }[conn]
  const { Icon } = map
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-semibold tracking-wider ${exec ? map.ex : map.cls}`}>
      <span className={`h-2 w-2 rounded-full ${exec ? '' : 'pulse-dot'} ${map.dot}`} />
      <Icon size={13} className={conn === 'connecting' ? 'animate-spin' : ''} />
      {map.text}
      <span className="hidden font-mono text-[10px] font-normal opacity-70 md:inline">{map.sub}</span>
    </span>
  )
}

function Toasts({ exec }) {
  const { toasts } = useParking()
  const icon = { ok: CheckCircle2, warn: AlertTriangle, info: Info }
  const tone = { ok: 'text-neon-emerald', warn: 'text-amber-300', info: 'text-neon-cyan' }
  return (
    <div className="pointer-events-none fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-2">
      {toasts.map((t) => {
        const Icon = icon[t.tone] || Info
        return (
          <div key={t.id} className={`toast-in flex items-center gap-2 rounded-xl px-4 py-2 text-xs ${exec ? 'border border-slate-700 bg-slate-900 shadow-lg' : 'glass-strong'} ${tone[t.tone] || tone.info}`}>
            <Icon size={14} /> <span className="text-slate-100">{t.text}</span>
          </div>
        )
      })}
    </div>
  )
}

export default function Layout() {
  const { conn } = useParking()
  const exec = useLocation().pathname.startsWith('/crm')

  const link = ({ isActive }) => exec
    ? `flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition ${
      isActive ? 'bg-slate-800 text-white' : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-100'}`
    : `flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-semibold uppercase tracking-widest transition ${
      isActive ? 'bg-neon-cyan/15 text-neon-cyan shadow-glow-cyan ring-1 ring-neon-cyan/40' : 'text-slate-400 hover:bg-white/5 hover:text-slate-100'}`

  return (
    <div className={`flex h-full flex-col ${exec ? 'bg-[#0f172a]' : 'bg-base bg-grid'}`}>
      <header
        className={`z-30 flex h-14 shrink-0 items-center justify-between gap-3 px-4 ${
          exec ? 'border-b border-slate-800 bg-[#0b1325]' : 'glass-strong rounded-none border-x-0 border-t-0'}`}
      >
        <div className="flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="h-8 w-8" />
          {exec ? (
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-wide text-white">Parkly</div>
              <div className="hidden text-[11px] text-slate-400 sm:block">Operations Console</div>
            </div>
          ) : (
            <div className="leading-tight">
              <div className="font-display text-sm font-bold tracking-[0.25em] text-white">PARKLY</div>
              <div className="label hidden sm:block">Admin // Digital Twin</div>
            </div>
          )}
        </div>
        <nav className="flex items-center gap-1.5">
          <NavLink to="/twin" className={link}><Box size={15} /> <span className="hidden sm:inline">3D Twin</span><span className="sm:hidden">3D</span></NavLink>
          <NavLink to="/crm" className={link}><BarChart3 size={15} /> CRM</NavLink>
        </nav>
        <ConnectionPill conn={conn} exec={exec} />
      </header>
      <main className="relative min-h-0 flex-1">
        <Outlet />
      </main>
      <Toasts exec={exec} />
    </div>
  )
}
