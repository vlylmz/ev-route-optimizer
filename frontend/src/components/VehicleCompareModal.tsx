import { useEffect, useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { postCompareVehicles } from '../services/api'
import type {
  CompareVehiclesResponse,
  StrategyName,
  VehicleSummary,
} from '../services/schemas'

interface Props {
  vehicles: VehicleSummary[]
  defaultVehicleId: string
  start: { lat: number; lon: number }
  end: { lat: number; lon: number }
  initialSocPct: number
  targetArrivalSocPct?: number | null
  strategy: StrategyName
  onClose: () => void
}

export function VehicleCompareModal({
  vehicles,
  defaultVehicleId,
  start,
  end,
  initialSocPct,
  targetArrivalSocPct,
  strategy,
  onClose,
}: Props) {
  const [selected, setSelected] = useState<string[]>(
    [defaultVehicleId, ...vehicles.slice(0, 3).map((v) => v.id)]
      .filter((id, i, arr) => arr.indexOf(id) === i)
      .slice(0, 3),
  )

  const compareM = useMutation<CompareVehiclesResponse>({
    mutationFn: () =>
      postCompareVehicles({
        vehicle_ids: selected,
        start,
        end,
        initial_soc_pct: initialSocPct,
        target_arrival_soc_pct: targetArrivalSocPct ?? null,
        strategy,
        use_ml: false,
      }),
  })

  // Modal açılırken otomatik çalıştır
  useEffect(() => {
    if (selected.length >= 2) {
      compareM.mutate()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggle = (id: string) => {
    setSelected((prev) => {
      if (prev.includes(id)) {
        return prev.filter((x) => x !== id)
      }
      if (prev.length >= 4) return prev
      return [...prev, id]
    })
  }

  const result = compareM.data
  const rows = result?.rows ?? []
  const cheapest = result?.cheapest_vehicle_id
  const fastest = result?.fastest_vehicle_id
  const efficient = result?.most_efficient_vehicle_id

  const sortedVehicles = useMemo(
    () => [...vehicles].sort((a, b) => a.name.localeCompare(b.name)),
    [vehicles],
  )

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 px-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between bg-gradient-to-r from-indigo-600 to-violet-600 px-5 py-4 text-white">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-indigo-100">
              A/B Karşılaştırma
            </div>
            <h3 className="text-lg font-bold">Aynı rotada farklı araçlar</h3>
            <div className="text-xs text-indigo-100/90">
              Strateji: <span className="font-semibold">{strategy}</span> · Başlangıç{' '}
              %{initialSocPct.toFixed(0)}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-white/80 hover:bg-white/15 hover:text-white"
            aria-label="Kapat"
          >
            ✕
          </button>
        </div>

        {/* Vehicle picker */}
        <div className="border-b border-slate-200 bg-slate-50 px-5 py-3">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-600">
            Karşılaştırılacak araçlar (2-4)
          </div>
          <div className="max-h-32 overflow-y-auto">
            <div className="grid grid-cols-2 gap-1">
              {sortedVehicles.map((v) => {
                const checked = selected.includes(v.id)
                return (
                  <label
                    key={v.id}
                    className={
                      'flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs ' +
                      (checked ? 'bg-indigo-100' : 'hover:bg-white')
                    }
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(v.id)}
                      className="h-3 w-3"
                    />
                    <span className="truncate">{v.name}</span>
                  </label>
                )
              })}
            </div>
          </div>
          <button
            onClick={() => compareM.mutate()}
            disabled={selected.length < 2 || compareM.isPending}
            className="mt-3 w-full rounded-md bg-indigo-600 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {compareM.isPending
              ? 'Hesaplanıyor…'
              : `${selected.length} aracı karşılaştır`}
          </button>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {compareM.isError && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
              Hata: {compareM.error.message}
            </div>
          )}

          {compareM.isPending && (
            <div className="py-8 text-center text-sm text-slate-500">
              Araçlar için rota planlanıyor…
            </div>
          )}

          {!compareM.isPending && rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="border-b-2 border-slate-200 text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-2 py-2 text-left">Araç</th>
                    <th className="px-2 py-2 text-right">Süre</th>
                    <th className="px-2 py-2 text-right">Şarj</th>
                    <th className="px-2 py-2 text-right">Durak</th>
                    <th className="px-2 py-2 text-right">Enerji</th>
                    <th className="px-2 py-2 text-right">Varış</th>
                    <th className="px-2 py-2 text-right">Maliyet</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr
                      key={r.vehicle_id}
                      className={
                        r.feasible
                          ? 'border-b border-slate-100 hover:bg-indigo-50/40'
                          : 'border-b border-slate-100 bg-red-50/40 text-slate-400'
                      }
                    >
                      <td className="px-2 py-2">
                        <div className="font-semibold text-slate-900">
                          {r.vehicle_name}
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {r.vehicle_id === cheapest && (
                            <Badge tone="amber">💰 En ucuz</Badge>
                          )}
                          {r.vehicle_id === fastest && (
                            <Badge tone="emerald">⏱ En hızlı</Badge>
                          )}
                          {r.vehicle_id === efficient && (
                            <Badge tone="indigo">🌿 En verimli</Badge>
                          )}
                          {!r.feasible && (
                            <Badge tone="red">
                              {r.error ?? 'Uygun değil'}
                            </Badge>
                          )}
                        </div>
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {r.feasible ? `${r.total_trip_minutes.toFixed(0)} dk` : '—'}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {r.feasible ? `${r.charging_minutes.toFixed(0)} dk` : '—'}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {r.feasible ? r.stop_count : '—'}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {r.feasible
                          ? `${r.total_energy_kwh.toFixed(1)} kWh`
                          : '—'}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {r.feasible ? `%${r.final_soc_pct.toFixed(0)}` : '—'}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums font-semibold text-amber-700">
                        {r.feasible ? `${r.total_cost_try.toFixed(0)} ₺` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!compareM.isPending && !compareM.isError && rows.length === 0 && (
            <div className="py-8 text-center text-xs text-slate-500">
              Yukarıdan en az 2 araç seç ve "Karşılaştır" butonuna bas.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Badge({
  tone,
  children,
}: {
  tone: 'amber' | 'emerald' | 'indigo' | 'red'
  children: React.ReactNode
}) {
  const cls = {
    amber: 'bg-amber-100 text-amber-800',
    emerald: 'bg-emerald-100 text-emerald-800',
    indigo: 'bg-indigo-100 text-indigo-800',
    red: 'bg-red-100 text-red-800',
  }[tone]
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-[9px] font-semibold ${cls}`}
    >
      {children}
    </span>
  )
}
