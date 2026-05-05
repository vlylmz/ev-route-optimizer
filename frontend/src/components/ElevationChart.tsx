import { useMemo } from 'react'

interface ElevationPoint {
  cumulative_distance_km: number
  elevation_m: number
}

interface HighlightStop {
  distance_along_route_km: number
  name?: string
}

interface Props {
  profile: ElevationPoint[]
  highlightedStops?: HighlightStop[]
  height?: number
  className?: string
}

/**
 * Rota üzerinde yükseklik profilini SVG line chart olarak çizer.
 * - X ekseni: kümülatif km
 * - Y ekseni: yükseklik (metre)
 * - Şarj durakları gri-dik çizgi olarak işaretlenir
 */
export function ElevationChart({
  profile,
  highlightedStops = [],
  height = 120,
  className = '',
}: Props) {
  const data = useMemo(() => {
    if (!profile || profile.length < 2) return null

    const points = profile
      .map((p) => ({
        km: Number(p.cumulative_distance_km) || 0,
        ele: Number(p.elevation_m) || 0,
      }))
      .filter((p) => Number.isFinite(p.km) && Number.isFinite(p.ele))

    if (points.length < 2) return null

    const maxKm = Math.max(...points.map((p) => p.km))
    let minEle = Math.min(...points.map((p) => p.ele))
    let maxEle = Math.max(...points.map((p) => p.ele))
    if (maxEle - minEle < 30) {
      // Düz arazi → yapay marj koy
      const mid = (maxEle + minEle) / 2
      minEle = mid - 50
      maxEle = mid + 50
    }
    return { points, maxKm, minEle, maxEle }
  }, [profile])

  if (!data) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/60 p-3 text-center text-[11px] text-slate-500">
        Eğim verisi yok
      </div>
    )
  }

  const W = 600 // viewBox width (responsive scale)
  const H = height
  const padL = 32
  const padR = 8
  const padT = 8
  const padB = 18

  const chartW = W - padL - padR
  const chartH = H - padT - padB

  const xScale = (km: number) => padL + (km / data.maxKm) * chartW
  const yScale = (ele: number) =>
    padT +
    chartH -
    ((ele - data.minEle) / (data.maxEle - data.minEle || 1)) * chartH

  const pathD =
    'M ' +
    data.points
      .map((p) => `${xScale(p.km).toFixed(1)} ${yScale(p.ele).toFixed(1)}`)
      .join(' L ')

  const areaD =
    pathD +
    ` L ${xScale(data.maxKm).toFixed(1)} ${(padT + chartH).toFixed(1)}` +
    ` L ${padL} ${(padT + chartH).toFixed(1)} Z`

  // Y ekseni etiketleri (3 değer: min, orta, max)
  const yTicks = [
    data.maxEle,
    (data.maxEle + data.minEle) / 2,
    data.minEle,
  ].map((v) => Math.round(v))

  return (
    <div className={`rounded-lg border border-slate-200 bg-white/80 p-2 ${className}`}>
      <div className="mb-1 flex items-center justify-between text-[10px] text-slate-500">
        <span className="font-semibold uppercase tracking-wider text-slate-600">
          📈 Yükseklik profili
        </span>
        <span>
          {Math.round(data.minEle)}–{Math.round(data.maxEle)} m · {data.maxKm.toFixed(0)} km
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-auto w-full"
        style={{ height }}
      >
        <defs>
          <linearGradient id="elevGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#10b981" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#10b981" stopOpacity="0.05" />
          </linearGradient>
        </defs>

        {/* Yatay grid */}
        {yTicks.map((t, i) => (
          <line
            key={i}
            x1={padL}
            y1={yScale(t)}
            x2={W - padR}
            y2={yScale(t)}
            stroke="#e2e8f0"
            strokeDasharray="2 3"
            strokeWidth="0.5"
          />
        ))}

        {/* Y ekseni etiketleri */}
        {yTicks.map((t, i) => (
          <text
            key={`yl-${i}`}
            x={padL - 4}
            y={yScale(t) + 3}
            fontSize="9"
            fill="#64748b"
            textAnchor="end"
          >
            {t}m
          </text>
        ))}

        {/* X ekseni etiketleri */}
        {[0, data.maxKm / 2, data.maxKm].map((km, i) => (
          <text
            key={`xl-${i}`}
            x={xScale(km)}
            y={H - 4}
            fontSize="9"
            fill="#64748b"
            textAnchor="middle"
          >
            {Math.round(km)} km
          </text>
        ))}

        {/* Dolgu alanı */}
        <path d={areaD} fill="url(#elevGrad)" />

        {/* Profil çizgisi */}
        <path
          d={pathD}
          fill="none"
          stroke="#059669"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />

        {/* Şarj durakları — dikey çizgi + nokta */}
        {highlightedStops.map((s, i) => {
          const x = xScale(
            Math.max(0, Math.min(s.distance_along_route_km, data.maxKm)),
          )
          // Bu km'deki yüksekliği bul (en yakın iki nokta arasına interpole)
          let stopEle = data.points[0].ele
          for (let j = 1; j < data.points.length; j++) {
            if (data.points[j].km >= s.distance_along_route_km) {
              const a = data.points[j - 1]
              const b = data.points[j]
              const t = b.km > a.km ? (s.distance_along_route_km - a.km) / (b.km - a.km) : 0
              stopEle = a.ele + (b.ele - a.ele) * t
              break
            }
            stopEle = data.points[j].ele
          }
          const y = yScale(stopEle)
          return (
            <g key={`stop-${i}`}>
              <line
                x1={x}
                y1={padT}
                x2={x}
                y2={padT + chartH}
                stroke="#4f46e5"
                strokeWidth="1"
                strokeDasharray="3 2"
                opacity="0.7"
              />
              <circle
                cx={x}
                cy={y}
                r={4}
                fill="#4f46e5"
                stroke="white"
                strokeWidth="1.5"
              />
              <text
                x={x}
                y={padT + 8}
                fontSize="9"
                fontWeight="bold"
                fill="#4f46e5"
                textAnchor="middle"
              >
                {i + 1}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
