import { useMemo, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { AlertCircle, Search, X } from 'lucide-react'
import { useParking } from '../store/ParkingContext.jsx'
import { useNow } from '../hooks/useNow.js'
import { fmtDateTime, fmtMinutes, fmtMoney, fmtTime } from '../lib/format.js'

const HOURS = Array.from({ length: 15 }, (_, i) => 8 + i) // 08:00 .. 22:00
const SLOT_COLORS = ['#3b82f6', '#38bdf8', '#818cf8', '#94a3b8']
const FILTERS = ['All', 'Active', 'Awaiting payment', 'Completed']

const TIP = {
  contentStyle: { background: '#0b1325', border: '1px solid #334155', borderRadius: 6, fontSize: 12, color: '#e2e8f0' },
  labelStyle: { color: '#94a3b8' },
  itemStyle: { color: '#e2e8f0' },
}

const STATUS_STYLE = {
  Active: 'bg-blue-500/10 text-blue-300 ring-blue-500/30',
  'Awaiting payment': 'bg-amber-500/10 text-amber-300 ring-amber-500/30',
  Completed: 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/30',
  Exception: 'bg-red-500/10 text-red-300 ring-red-500/30',
}

function Card({ title, aside, children, className = '' }) {
  return (
    <section className={`rounded-lg border border-slate-700/50 bg-[#111c33] ${className}`}>
      {(title || aside) && (
        <header className="flex items-center justify-between border-b border-slate-700/50 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
          {aside && <span className="text-xs text-slate-400">{aside}</span>}
        </header>
      )}
      {children}
    </section>
  )
}

function Kpi({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-slate-700/50 bg-[#111c33] px-5 py-4">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-white">{value}</div>
      <div className="mt-1 text-xs text-slate-400">{sub}</div>
    </div>
  )
}

function Empty({ children }) {
  return <div className="grid h-full place-items-center px-4 text-center text-sm text-slate-500">{children}</div>
}

function DetailsModal({ row, currency, onClose }) {
  if (!row) return null
  const items = [
    ['Session ID', `S-${row.id}`], ['License plate', row.plate], ['Slot', row.slotIndex >= 0 ? `#${row.slotIndex + 1}` : '—'],
    ['Status', row.status], ['Entry', fmtDateTime(row.entryAt)], ['Exit', fmtDateTime(row.exitAt)],
    ['Paid', fmtDateTime(row.paidAt)], ['Duration', row.durationSec != null ? fmtMinutes(row.durationSec / 60) : '—'],
    ['Fee', row.fee != null ? fmtMoney(row.fee, currency) : '—'], ['Type', row.staff ? 'Staff' : 'Customer'],
  ]
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/70 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-lg border border-slate-700 bg-[#111c33] shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-700/60 px-5 py-3">
          <h3 className="text-sm font-semibold text-white">Session details</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white" aria-label="Close"><X size={18} /></button>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 p-5">
          {items.map(([k, v]) => (
            <div key={k}>
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{k}</dt>
              <dd className="mt-0.5 text-sm tabular-nums text-slate-100">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}

export default function CrmPage() {
  const { conn, live, crm } = useParking()
  const now = useNow(30000)
  const [filter, setFilter] = useState('All')
  const [query, setQuery] = useState('')
  const [detail, setDetail] = useState(null)
  const { rows, currency } = crm

  const midnight = useMemo(() => { const d = new Date(now); d.setHours(0, 0, 0, 0); return d }, [now])
  const today = useMemo(() => rows.filter((r) => r.entryAt && r.entryAt >= midnight), [rows, midnight])

  const kpi = useMemo(() => {
    const paid = rows.filter((r) => (r.rawStatus === 'PAID' || r.rawStatus === 'COMPLETED') && r.paidAt && r.paidAt >= midnight)
    const revenue = paid.reduce((a, r) => a + (r.fee || 0), 0)
    const timed = today.filter((r) => r.durationSec != null)
    const avg = timed.length ? timed.reduce((a, r) => a + r.durationSec, 0) / timed.length / 60 : null
    const total = live.slots.length
    const occupied = live.slots.filter((s) => s.status === 'OCCUPIED').length
    return {
      revenue, paidCount: paid.length, avg, timedCount: timed.length, occupied, total,
      active: today.filter((r) => r.status === 'Active').length,
    }
  }, [rows, today, midnight, live])

  const hourly = useMemo(() => {
    const data = HOURS.map((h) => ({ hour: `${String(h).padStart(2, '0')}:00`, h, vehicles: 0 }))
    today.forEach((r) => { const b = data.find((d) => d.h === r.entryAt.getHours()); if (b) b.vehicles += 1 })
    const peak = Math.max(0, ...data.map((d) => d.vehicles))
    return { data: data.map((d) => ({ ...d, peak: peak > 0 && d.vehicles === peak })), peak }
  }, [today])

  const usage = useMemo(() => {
    const counts = live.slots.map(() => 0)
    today.forEach((r) => { if (r.slotIndex >= 0 && r.slotIndex < counts.length) counts[r.slotIndex] += 1 })
    const total = counts.reduce((a, b) => a + b, 0)
    return { total, items: counts.map((v, i) => ({ name: `Slot ${i + 1}`, value: v, pct: total ? Math.round((v / total) * 100) : 0 })) }
  }, [today, live])

  const visible = rows.filter((r) => {
    if (filter !== 'All' && r.status !== filter) return false
    const q = query.replace(/\s+/g, '').toLowerCase()
    if (!q) return true
    return r.plate.replace(/\s+/g, '').toLowerCase().includes(q) || `s-${r.id}`.includes(q) || String(r.id) === q
  })

  const banner = conn !== 'online'
    ? 'Live connection unavailable — figures update again when the WebSocket reconnects.'
    : crm.status === 'error' ? `Session history could not be loaded (${crm.error}). If the backend requires a service token, set VITE_SERVICE_TOKEN.` : null

  return (
    <div className="h-full overflow-y-auto font-sans">
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-white">Operations overview</h1>
            <p className="text-sm text-slate-400">
              {new Date(now).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
            </p>
          </div>
        </div>

        {banner && (
          <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-200">
            <AlertCircle size={16} className="mt-0.5 shrink-0" /> {banner}
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi label="Revenue today" value={fmtMoney(kpi.revenue, currency)} sub={`${kpi.paidCount} paid session${kpi.paidCount === 1 ? '' : 's'}`} />
          <Kpi label="Total sessions" value={String(today.length)} sub={`${kpi.active} currently active`} />
          <Kpi label="Avg. duration" value={kpi.avg == null ? '—' : fmtMinutes(kpi.avg)} sub={kpi.timedCount ? `across ${kpi.timedCount} billed sessions` : 'no billed sessions yet'} />
          <Kpi
            label="Occupancy rate"
            value={`${kpi.total ? Math.round((kpi.occupied / kpi.total) * 100) : 0}%`}
            sub={`${kpi.occupied} of ${kpi.total} slots occupied now`}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card title="Hourly traffic" aside="vehicle entries per hour · 08:00–22:00" className="lg:col-span-2">
            <div className="h-72 p-4">
              {today.length === 0 ? (
                <Empty>No entries recorded today.</Empty>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={hourly.data} margin={{ top: 8, right: 4, left: -22, bottom: 0 }}>
                    <CartesianGrid stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="hour" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={{ stroke: '#334155' }} tickLine={false} interval={0} />
                    <YAxis allowDecimals={false} tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip {...TIP} cursor={{ fill: 'rgba(148,163,184,.08)' }} />
                    <Bar dataKey="vehicles" name="Vehicles" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                      {hourly.data.map((d) => <Cell key={d.hour} fill={d.peak ? '#60a5fa' : '#3b82f6'} fillOpacity={d.peak ? 1 : 0.55} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </Card>

          <Card title="Slot utilization" aside="share of today’s sessions">
            <div className="p-4">
              <div className="relative h-48">
                {usage.total === 0 ? (
                  <Empty>No sessions yet.</Empty>
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={usage.items} dataKey="value" innerRadius="64%" outerRadius="92%" paddingAngle={2} stroke="#111c33" strokeWidth={2} isAnimationActive={false}>
                          {usage.items.map((_, i) => <Cell key={i} fill={SLOT_COLORS[i % SLOT_COLORS.length]} />)}
                        </Pie>
                        <Tooltip {...TIP} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
                      <div>
                        <div className="text-2xl font-semibold tabular-nums text-white">{usage.total}</div>
                        <div className="text-[11px] uppercase tracking-wider text-slate-400">sessions</div>
                      </div>
                    </div>
                  </>
                )}
              </div>
              <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
                {usage.items.map((u, i) => (
                  <li key={u.name} className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-2 text-slate-300">
                      <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SLOT_COLORS[i % SLOT_COLORS.length] }} /> {u.name}
                    </span>
                    <span className="tabular-nums text-slate-400">{u.pct}%</span>
                  </li>
                ))}
              </ul>
            </div>
          </Card>
        </div>

        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-700/50 px-5 py-3">
            <h2 className="text-sm font-semibold text-slate-100">Session history</h2>
            <div className="flex flex-wrap items-center gap-3">
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search by plate…"
                  className="w-56 rounded-md border border-slate-700 bg-slate-900 py-2 pl-9 pr-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div className="flex rounded-md border border-slate-700 bg-slate-900 p-0.5">
                {FILTERS.map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`rounded px-3 py-1.5 text-xs font-medium transition ${filter === f ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-100'}`}
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm tabular-nums">
              <thead>
                <tr className="bg-slate-800/50 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  {['Session ID', 'License plate', 'Entry time', 'Slot #', 'Status', 'Fee', 'Actions'].map((h) => (
                    <th key={h} className={`px-5 py-3 ${h === 'Fee' ? 'text-right' : ''}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {visible.map((r) => (
                  <tr key={r.id} className="odd:bg-transparent even:bg-slate-900/30 hover:bg-slate-800/40">
                    <td className="px-5 py-3 text-slate-400">S-{r.id}</td>
                    <td className="px-5 py-3 font-semibold tracking-wide text-white">
                      {r.plate}
                      {r.staff && <span className="ml-2 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] font-medium uppercase text-slate-300">Staff</span>}
                    </td>
                    <td className="px-5 py-3">
                      <div className="text-slate-100">{fmtTime(r.entryAt)}</div>
                      <div className="text-[11px] text-slate-500">
                        {r.entryAt ? r.entryAt.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : ''}
                        {r.durationSec != null ? ` · ${fmtMinutes(r.durationSec / 60)}` : ''}
                      </div>
                    </td>
                    <td className="px-5 py-3 text-slate-200">{r.slotIndex >= 0 ? `#${r.slotIndex + 1}` : '—'}</td>
                    <td className="px-5 py-3">
                      <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_STYLE[r.status]}`}>{r.status}</span>
                    </td>
                    <td className="px-5 py-3 text-right font-semibold text-slate-100">{r.fee != null ? fmtMoney(r.fee, currency) : '—'}</td>
                    <td className="px-5 py-3">
                      <button onClick={() => setDetail(r)} className="rounded border border-slate-600 px-2.5 py-1 text-xs font-medium text-slate-200 transition hover:border-slate-400 hover:bg-slate-800">
                        View
                      </button>
                    </td>
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-5 py-12 text-center text-sm text-slate-500">
                      {rows.length === 0 ? 'No sessions yet. Records appear here as vehicles enter and leave.' : 'No sessions match the current filters.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="border-t border-slate-800 px-5 py-3 text-xs text-slate-500">{visible.length} of {rows.length} sessions</div>
        </Card>
      </div>
      <DetailsModal row={detail} currency={currency} onClose={() => setDetail(null)} />
    </div>
  )
}
