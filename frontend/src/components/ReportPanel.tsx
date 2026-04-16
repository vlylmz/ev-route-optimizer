import type { OptimizeResponse } from '../services/schemas'
import { ProfileCard } from './ProfileCard'

interface Props {
  result: OptimizeResponse
}

export function ReportPanel({ result }: Props) {
  const { profiles, recommended_profile } = result

  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            {result.vehicle_name}
          </h2>
          <p className="text-sm text-slate-600">
            {result.total_distance_km.toFixed(1)} km · başlangıç{' '}
            {result.initial_soc_pct.toFixed(0)}% · varış{' '}
            {result.final_soc_pct.toFixed(0)}% · toplam{' '}
            {result.total_energy_kwh.toFixed(2)} kWh
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs font-semibold uppercase text-slate-500">
            Durum
          </div>
          <div
            className={
              'text-sm font-semibold ' +
              (result.status === 'ok' ? 'text-emerald-600' : 'text-amber-600')
            }
          >
            {result.status === 'ok' ? 'Plan hazır' : result.status}
          </div>
          {result.used_ml && (
            <div className="mt-1 text-xs text-indigo-600">
              ML: {result.model_version ?? 'aktif'} ·{' '}
              {result.ml_segment_count} ML / {result.heuristic_segment_count}{' '}
              formül segment
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {profiles.map((p) => (
          <ProfileCard
            key={p.key}
            card={p}
            recommended={p.key === recommended_profile}
          />
        ))}
      </div>
    </section>
  )
}
