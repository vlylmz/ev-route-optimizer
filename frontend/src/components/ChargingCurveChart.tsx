import { useMemo } from 'react'
import type { ChargingCurvePoint } from '../services/schemas'

interface Props {
  points: ChargingCurvePoint[]
  totalMinutes: number
  vehicleMaxKw?: number
  height?: number
  className?: string
}

/**
 * Şarj seansı grafiği:
 * - X ekseni: zaman (dakika)
 * - Sol Y ekseni: SOC % (mavi alan)
 * - Sağ Y ekseni: kW (turuncu çizgi, kW = vehicle accept × station limit)
 */
export function ChargingCurveChart({
  points,
  totalMinutes,
  vehicleMaxKw,
  height = 110,
  className = '',
}: Props) {
  const chart = useMemo(() => {
    if (!points || points.length < 2) return null
    const maxKw = Math.max(
      vehicleMaxKw ?? 0,
      ...points.map((p) => p.power_kw),
    )
    const maxTime = Math.max(totalMinutes, points[points.length - 1].time_min, 1)
    return { maxKw, maxTime }
  }, [points, totalMinutes, vehicleMaxKw])

  if (!chart) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/60 p-3 text-center text-[11px] text-slate-500">
        Şarj eğrisi hesaplanıyor…
      </div>
    )
  }

  const W = 320
  const H = height
  const padL = 28
  const padR = 28
  const padT = 8
  const padB = 18

  const cw = W - padL - padR
  const ch = H - padT - padB

  const xScale = (t: number) => padL + (t / chart.maxTime) * cw
  const ySoc = (s: number) => padT + ch - (s / 100) * ch
  const yKw = (kw: number) => padT + ch - (kw / chart.maxKw) * ch

  const socPath =
    'M ' +
    points
      .map((p) => `${xScale(p.time_min).toFixed(1)} ${ySoc(p.soc_pct).toFixed(1)}`)
      .join(' L ')
  const socArea =
    socPath +
    ` L ${xScale(chart.maxTime).toFixed(1)} ${(padT + ch).toFixed(1)}` +
    ` L ${padL} ${(padT + ch).toFixed(1)} Z`

  const kwPath =
    'M ' +
    points
      .map((p) => `${xScale(p.time_min).toFixed(1)} ${yKw(p.power_kw).toFixed(1)}`)
      .join(' L ')

  return (
    <div className={`rounded-lg border border-slate-200 bg-white/80 p-2 ${className}`}>
      <div className="mb-1 flex items-center justify-between text-[10px] text-slate-500">
        <span className="font-semibold uppercase tracking-wider">Şarj Eğrisi</span>
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-indigo-400/80" />
            SOC
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-3 rounded-sm bg-amber-500" />
            kW
          </span>
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-auto w-full"
        style={{ height }}
      >
        <defs>
          <linearGradient id="socGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6366f1" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#6366f1" stopOpacity="0.05" />
          </linearGradient>
        </defs>

        {/* Grid */}
        {[0, 25, 50, 75, 100].map((s) => (
          <line
            key={s}
            x1={padL}
            y1={ySoc(s)}
            x2={W - padR}
            y2={ySoc(s)}
            stroke="#e2e8f0"
            strokeDasharray="2 3"
            strokeWidth="0.5"
          />
        ))}

        {/* SOC area */}
        <path d={socArea} fill="url(#socGrad)" />
        <path d={socPath} fill="none" stroke="#6366f1" strokeWidth="1.5" />

        {/* kW line */}
        <path d={kwPath} fill="none" stroke="#f59e0b" strokeWidth="1.5" />

        {/* Sol Y etiketleri (SOC) */}
        {[0, 50, 100].map((s) => (
          <text
            key={`s-${s}`}
            x={padL - 3}
            y={ySoc(s) + 3}
            fontSize="9"
            fill="#64748b"
            textAnchor="end"
          >
            {s}%
          </text>
        ))}

        {/* Sağ Y etiketleri (kW) */}
        {[0, Math.round(chart.maxKw / 2), Math.round(chart.maxKw)].map((kw, i) => (
          <text
            key={`k-${i}`}
            x={W - padR + 3}
            y={yKw(kw) + 3}
            fontSize="9"
            fill="#b45309"
            textAnchor="start"
          >
            {kw}
          </text>
        ))}

        {/* X ekseni */}
        {[0, chart.maxTime / 2, chart.maxTime].map((t, i) => (
          <text
            key={`t-${i}`}
            x={xScale(t)}
            y={H - 4}
            fontSize="9"
            fill="#64748b"
            textAnchor="middle"
          >
            {Math.round(t)} dk
          </text>
        ))}
      </svg>
    </div>
  )
}
