import type { VehicleSummary } from '../services/schemas'

interface Props {
  vehicles: VehicleSummary[]
  value: string
  onChange: (id: string) => void
  isLoading?: boolean
  isError?: boolean
}

export function VehicleSelect({
  vehicles,
  value,
  onChange,
  isLoading,
  isError,
}: Props) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor="vehicle" className="text-sm font-medium text-slate-700">
        Araç
      </label>
      <select
        id="vehicle"
        className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-60"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={isLoading || isError}
      >
        {isLoading && <option>Yükleniyor…</option>}
        {isError && <option>Araç listesi alınamadı</option>}
        {!isLoading && !isError && vehicles.length === 0 && (
          <option>Araç bulunamadı</option>
        )}
        {!isLoading &&
          !isError &&
          vehicles.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name} · {v.usable_battery_kwh} kWh · {v.max_dc_charge_kw} kW DC
            </option>
          ))}
      </select>
    </div>
  )
}
