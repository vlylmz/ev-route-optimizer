import { useState } from 'react'
import { VehicleSelect } from './VehicleSelect'
import type { OptimizeRequest, VehicleSummary, StrategyName } from '../services/schemas'

interface Props {
  vehicles: VehicleSummary[]
  vehiclesLoading?: boolean
  vehiclesError?: boolean
  onSubmit: (req: OptimizeRequest) => void
  isSubmitting?: boolean
}

const DEFAULT_PRESETS = [
  {
    label: 'Ankara → İstanbul',
    start: { lat: 39.92, lon: 32.85 },
    end: { lat: 41.01, lon: 28.97 },
  },
  {
    label: 'İstanbul → İzmir',
    start: { lat: 41.01, lon: 28.97 },
    end: { lat: 38.42, lon: 27.14 },
  },
  {
    label: 'Kısa — Çankaya → Keçiören',
    start: { lat: 39.91, lon: 32.86 },
    end: { lat: 39.99, lon: 32.87 },
  },
] as const

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
}: Props) {
  const [vehicleId, setVehicleId] = useState<string>('')
  const [startLat, setStartLat] = useState('39.92')
  const [startLon, setStartLon] = useState('32.85')
  const [endLat, setEndLat] = useState('41.01')
  const [endLon, setEndLon] = useState('28.97')
  const [initialSoc, setInitialSoc] = useState('80')
  const [strategies, setStrategies] = useState<StrategyName[]>([
    'fast',
    'efficient',
    'balanced',
  ])
  const [useMl, setUseMl] = useState(false)

  // Araç listesi yüklendikten sonra varsayılan seçim
  const effectiveVehicleId =
    vehicleId || (vehicles.length > 0 ? vehicles[0].id : '')

  const toggleStrategy = (key: StrategyName) => {
    setStrategies((prev) =>
      prev.includes(key) ? prev.filter((s) => s !== key) : [...prev, key],
    )
  }

  const applyPreset = (preset: (typeof DEFAULT_PRESETS)[number]) => {
    setStartLat(String(preset.start.lat))
    setStartLon(String(preset.start.lon))
    setEndLat(String(preset.end.lat))
    setEndLon(String(preset.end.lon))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!effectiveVehicleId) return
    if (strategies.length === 0) return

    onSubmit({
      vehicle_id: effectiveVehicleId,
      start: { lat: parseFloat(startLat), lon: parseFloat(startLon) },
      end: { lat: parseFloat(endLat), lon: parseFloat(endLon) },
      initial_soc_pct: parseFloat(initialSoc),
      strategies,
      use_ml: useMl,
    })
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <h2 className="text-lg font-semibold text-slate-900">Rota Planı</h2>

      <VehicleSelect
        vehicles={vehicles}
        value={effectiveVehicleId}
        onChange={setVehicleId}
        isLoading={vehiclesLoading}
        isError={vehiclesError}
      />

      <div className="flex flex-wrap gap-2">
        {DEFAULT_PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => applyPreset(p)}
            className="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Başlangıç lat" value={startLat} onChange={setStartLat} />
        <Field label="Başlangıç lon" value={startLon} onChange={setStartLon} />
        <Field label="Bitiş lat" value={endLat} onChange={setEndLat} />
        <Field label="Bitiş lon" value={endLon} onChange={setEndLon} />
      </div>

      <Field
        label="Başlangıç SOC (%)"
        value={initialSoc}
        onChange={setInitialSoc}
        type="number"
        min="0"
        max="100"
      />

      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium text-slate-700">
          Stratejiler
        </legend>
        <div className="flex gap-2">
          {STRATEGY_LIST.map((s) => {
            const active = strategies.includes(s.key)
            return (
              <button
                key={s.key}
                type="button"
                onClick={() => toggleStrategy(s.key)}
                className={
                  'rounded-md px-3 py-1.5 text-sm font-medium transition ' +
                  (active
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200')
                }
              >
                {s.label}
              </button>
            )
          })}
        </div>
      </fieldset>

      <label className="flex items-center gap-2 text-sm text-slate-700">
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
        disabled={isSubmitting || !effectiveVehicleId || strategies.length === 0}
        className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isSubmitting ? 'Hesaplanıyor…' : 'Rotayı Optimize Et'}
      </button>
    </form>
  )
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  ...rest
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  min?: string
  max?: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-slate-600">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        {...rest}
      />
    </div>
  )
}
