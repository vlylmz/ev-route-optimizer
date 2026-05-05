import { useEffect, useState } from 'react'
import { VehicleSelect } from './VehicleSelect'
import { LocationSearchInput } from './LocationSearchInput'
import type {
  GeocodeResultItem,
  OptimizeRequest,
  StrategyName,
  VehicleSummary,
} from '../services/schemas'

interface Props {
  vehicles: VehicleSummary[]
  vehiclesLoading?: boolean
  vehiclesError?: boolean
  onSubmit: (
    req: OptimizeRequest,
    extra: { start: GeocodeResultItem; end: GeocodeResultItem },
  ) => void
  isSubmitting?: boolean
  presetStart?: GeocodeResultItem | null
  presetEnd?: GeocodeResultItem | null
  presetVehicleId?: string | null
  presetInitialSocPct?: number | null
  presetTargetArrivalSocPct?: number | null
}

const DEFAULT_PRESETS: {
  label: string
  start: GeocodeResultItem
  end: GeocodeResultItem
}[] = [
  {
    label: 'Ankara → İstanbul',
    start: {
      display_name: 'Ankara',
      name: 'Ankara',
      lat: 39.92,
      lon: 32.85,
      type: 'city',
      importance: 0.7,
      country_code: 'tr',
    },
    end: {
      display_name: 'İstanbul',
      name: 'İstanbul',
      lat: 41.01,
      lon: 28.97,
      type: 'city',
      importance: 0.7,
      country_code: 'tr',
    },
  },
  {
    label: 'İstanbul → İzmir',
    start: {
      display_name: 'İstanbul',
      name: 'İstanbul',
      lat: 41.01,
      lon: 28.97,
      type: 'city',
      importance: 0.7,
      country_code: 'tr',
    },
    end: {
      display_name: 'İzmir',
      name: 'İzmir',
      lat: 38.42,
      lon: 27.14,
      type: 'city',
      importance: 0.7,
      country_code: 'tr',
    },
  },
  {
    label: 'Çankaya → Keçiören',
    start: {
      display_name: 'Çankaya, Ankara',
      name: 'Çankaya',
      lat: 39.91,
      lon: 32.86,
      type: 'suburb',
      importance: 0.5,
      country_code: 'tr',
    },
    end: {
      display_name: 'Keçiören, Ankara',
      name: 'Keçiören',
      lat: 39.99,
      lon: 32.87,
      type: 'suburb',
      importance: 0.5,
      country_code: 'tr',
    },
  },
]

const STRATEGY_LIST: { key: StrategyName; label: string }[] = [
  { key: 'fast', label: 'Hızlı' },
  { key: 'efficient', label: 'Verimli' },
  { key: 'balanced', label: 'Dengeli' },
]

export function RouteForm({
  vehicles,
  vehiclesLoading,
  vehiclesError,
  onSubmit,
  isSubmitting,
  presetStart,
  presetEnd,
  presetVehicleId,
  presetInitialSocPct,
  presetTargetArrivalSocPct,
}: Props) {
  const [vehicleId, setVehicleId] = useState<string>('')
  const [start, setStart] = useState<GeocodeResultItem | null>(null)
  const [end, setEnd] = useState<GeocodeResultItem | null>(null)
  const [initialSoc, setInitialSoc] = useState('80')
  const [targetArrivalSoc, setTargetArrivalSoc] = useState<number>(20)

  // Geçmişten bir rota seçildiğinde formu doldur
  useEffect(() => {
    if (presetStart) setStart(presetStart)
    if (presetEnd) setEnd(presetEnd)
    if (presetVehicleId) setVehicleId(presetVehicleId)
    if (presetInitialSocPct != null) setInitialSoc(String(presetInitialSocPct))
    if (presetTargetArrivalSocPct != null) {
      setTargetArrivalSoc(presetTargetArrivalSocPct)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetStart, presetEnd, presetVehicleId, presetInitialSocPct])
  const [strategies, setStrategies] = useState<StrategyName[]>([
    'fast',
    'efficient',
    'balanced',
  ])
  const [useMl, setUseMl] = useState(false)

  const effectiveVehicleId =
    vehicleId || (vehicles.length > 0 ? vehicles[0].id : '')

  const toggleStrategy = (key: StrategyName) => {
    setStrategies((prev) =>
      prev.includes(key) ? prev.filter((s) => s !== key) : [...prev, key],
    )
  }

  const applyPreset = (preset: (typeof DEFAULT_PRESETS)[number]) => {
    setStart(preset.start)
    setEnd(preset.end)
  }

  const canSubmit =
    !!effectiveVehicleId && !!start && !!end && strategies.length > 0

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || !start || !end) return

    onSubmit(
      {
        vehicle_id: effectiveVehicleId,
        start: { lat: start.lat, lon: start.lon },
        end: { lat: end.lat, lon: end.lon },
        initial_soc_pct: parseFloat(initialSoc),
        target_arrival_soc_pct: targetArrivalSoc,
        strategies,
        use_ml: useMl,
      },
      { start, end },
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white/70 p-4 shadow-sm backdrop-blur"
    >
      <VehicleSelect
        vehicles={vehicles}
        value={effectiveVehicleId}
        onChange={setVehicleId}
        isLoading={vehiclesLoading}
        isError={vehiclesError}
      />

      <div className="flex flex-wrap gap-1.5">
        {DEFAULT_PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => applyPreset(p)}
            className="rounded-full border border-indigo-200 bg-indigo-50/80 px-2.5 py-1 text-[11px] font-medium text-indigo-700 transition hover:bg-indigo-100"
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-3">
        <LocationSearchInput
          label="🅰 Başlangıç"
          placeholder="Şehir, ilçe, yer adı…"
          value={start}
          onChange={setStart}
        />
        <LocationSearchInput
          label="🅱 Varış"
          placeholder="Şehir, ilçe, yer adı…"
          value={end}
          onChange={setEnd}
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-600">
            🔋 Başlangıç SOC
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min="0"
              max="100"
              value={initialSoc}
              onChange={(e) => setInitialSoc(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <span className="text-xs text-slate-500">%</span>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-600">
            🎯 Varış SOC (min)
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min="0"
              max="100"
              value={targetArrivalSoc}
              onChange={(e) =>
                setTargetArrivalSoc(
                  Math.max(0, Math.min(100, Number(e.target.value) || 0)),
                )
              }
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <span className="text-xs text-slate-500">%</span>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={targetArrivalSoc}
          onChange={(e) => setTargetArrivalSoc(parseInt(e.target.value, 10))}
          className="h-2 w-full accent-indigo-600"
        />
        <div className="flex justify-between text-[10px] text-slate-400">
          <span>%0</span>
          <span className="font-semibold text-indigo-600">
            Varışta minimum {targetArrivalSoc}%
          </span>
          <span>%100</span>
        </div>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-xs font-medium text-slate-600">
          Stratejiler
        </legend>
        <div className="flex gap-1.5">
          {STRATEGY_LIST.map((s) => {
            const active = strategies.includes(s.key)
            return (
              <button
                key={s.key}
                type="button"
                onClick={() => toggleStrategy(s.key)}
                className={
                  'flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition ' +
                  (active
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200')
                }
              >
                {s.label}
              </button>
            )
          })}
        </div>
      </fieldset>

      <label className="flex items-center gap-2 text-xs text-slate-700">
        <input
          type="checkbox"
          checked={useMl}
          onChange={(e) => setUseMl(e.target.checked)}
          className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
        />
        ML modelini kullan
      </label>

      <button
        type="submit"
        disabled={isSubmitting || !canSubmit}
        className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isSubmitting ? 'Hesaplanıyor…' : 'Rotayı Optimize Et'}
      </button>
    </form>
  )
}
