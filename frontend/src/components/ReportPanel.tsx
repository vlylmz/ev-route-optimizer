import type { OptimizeResponse, RecommendedStop } from '../services/schemas'
import { ProfileCard } from './ProfileCard'
import type { Reservation } from './ReservationDialog'

interface Props {
  result: OptimizeResponse
  reservations?: Record<string, Reservation>
  onReserve?: (strategyKey: string, stopIdx: number, stop: RecommendedStop) => void
  activeProfileKey?: string | null
  onSelectProfile?: (key: string) => void
}

export function ReportPanel({
  result,
  reservations,
  onReserve,
  activeProfileKey,
  onSelectProfile,
}: Props) {
  const { profiles, recommended_profile } = result

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white/70 p-3 shadow-sm backdrop-blur">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-bold text-slate-900">
            {result.vehicle_name}
          </h2>
          <p className="text-[11px] text-slate-600">
            {result.total_distance_km.toFixed(1)} km · başlangıç{' '}
            {result.initial_soc_pct.toFixed(0)}% · varış{' '}
            {result.final_soc_pct.toFixed(0)}% · {result.total_energy_kwh.toFixed(2)}{' '}
            kWh
          </p>
        </div>
        <div className="text-right">
          <div className="text-[10px] font-semibold uppercase text-slate-500">
            Durum
          </div>
          <div
            className={
              'text-xs font-bold ' +
              (result.status === 'ok' ? 'text-emerald-600' : 'text-amber-600')
            }
          >
            {result.status === 'ok' ? 'Plan hazır' : result.status}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        {profiles.map((p) => (
          <ProfileCard
            key={p.key}
            card={p}
            recommended={p.key === recommended_profile}
            active={activeProfileKey === p.key}
            onSelect={
              onSelectProfile ? () => onSelectProfile(p.key) : undefined
            }
            reservations={reservations}
            onReserve={
              onReserve
                ? (stop) => {
                    const idx = p.recommended_stops.findIndex(
                      (s) =>
                        s.distance_along_route_km ===
                          stop.distance_along_route_km &&
                        s.name === stop.name,
                    )
                    if (idx >= 0) onReserve(p.key, idx, stop)
                  }
                : undefined
            }
          />
        ))}
      </div>
    </section>
  )
}
