import { useEffect, useState } from 'react'

export interface RecommendedStop {
  name: string
  operator?: string | null
  distance_along_route_km: number
  detour_distance_km?: number
  detour_minutes?: number
  arrival_soc_percent: number
  target_soc_percent: number
  charge_minutes: number
  power_kw: number
  energy_kwh?: number
  cost_try?: number
}

export interface Reservation {
  stopName: string
  startTime: string // HH:MM
  durationMinutes: number
  powerKw: number
  targetSocPercent: number
  reservationId: string
}

interface Props {
  stop: RecommendedStop | null
  existingReservation: Reservation | null
  onClose: () => void
  onConfirm: (reservation: Reservation) => void
  onCancel: () => void
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function nextQuarterHour(): string {
  const now = new Date()
  const minutes = Math.ceil(now.getMinutes() / 15) * 15
  if (minutes === 60) {
    return `${pad(now.getHours() + 1)}:00`
  }
  return `${pad(now.getHours())}:${pad(minutes)}`
}

function generateId(): string {
  // Basit, kullanıcı görebileceği uniq ID
  return (
    'RZ-' +
    Math.floor(Math.random() * 0xffffff)
      .toString(36)
      .toUpperCase()
      .padStart(5, '0')
  )
}

export function ReservationDialog({
  stop,
  existingReservation,
  onClose,
  onConfirm,
  onCancel,
}: Props) {
  const [time, setTime] = useState<string>(
    existingReservation?.startTime ?? nextQuarterHour(),
  )
  const [duration, setDuration] = useState<number>(
    existingReservation?.durationMinutes ?? Math.round(stop?.charge_minutes ?? 20),
  )

  useEffect(() => {
    if (existingReservation) {
      setTime(existingReservation.startTime)
      setDuration(existingReservation.durationMinutes)
    } else if (stop) {
      setDuration(Math.round(stop.charge_minutes))
    }
  }, [stop, existingReservation])

  if (!stop) return null

  const isEditing = !!existingReservation

  const handleConfirm = () => {
    onConfirm({
      stopName: stop.name,
      startTime: time,
      durationMinutes: duration,
      powerKw: stop.power_kw,
      targetSocPercent: stop.target_soc_percent,
      reservationId: existingReservation?.reservationId ?? generateId(),
    })
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 px-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="bg-gradient-to-r from-emerald-600 to-teal-600 px-5 py-4 text-white">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-100">
            {isEditing ? 'Rezervasyon Düzenle' : 'Şarj Rezervasyonu'}
          </div>
          <h3 className="text-lg font-bold leading-tight">{stop.name}</h3>
          <div className="mt-1 flex items-center gap-3 text-xs text-emerald-50/90">
            <span>📍 {stop.distance_along_route_km.toFixed(1)} km'de</span>
            <span>⚡ {stop.power_kw} kW</span>
          </div>
        </div>

        {/* Body */}
        <div className="space-y-4 px-5 py-4">
          {/* Plan özeti */}
          <div className="grid grid-cols-3 gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-center text-xs">
            <Stat label="Varış SOC" value={`%${stop.arrival_soc_percent.toFixed(0)}`} />
            <Stat label="Hedef SOC" value={`%${stop.target_soc_percent.toFixed(0)}`} />
            <Stat label="Sapma" value={`${(stop.detour_distance_km ?? 0).toFixed(1)} km`} />
          </div>

          {/* Saat */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-600">
              Geliş saati
            </label>
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
            <span className="text-[10px] text-slate-500">
              Şarj noktası bu saat için 15 dakika tutulur (mock).
            </span>
          </div>

          {/* Süre */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-600">
              Şarj süresi: <span className="font-semibold">{duration} dk</span>
            </label>
            <input
              type="range"
              min={5}
              max={90}
              step={5}
              value={duration}
              onChange={(e) => setDuration(parseInt(e.target.value, 10))}
              className="h-2 w-full"
            />
            <div className="flex justify-between text-[10px] text-slate-400">
              <span>5 dk</span>
              <span>Önerilen: {Math.round(stop.charge_minutes)} dk</span>
              <span>90 dk</span>
            </div>
          </div>

          {/* Tahmini enerji */}
          <div className="rounded-lg border border-emerald-100 bg-emerald-50/70 px-3 py-2 text-xs text-emerald-800">
            ⚡ Tahmini eklenecek enerji:{' '}
            <span className="font-bold">
              {((duration / 60) * stop.power_kw * 0.85).toFixed(1)} kWh
            </span>
            <span className="text-emerald-600">
              {' '}
              ({stop.power_kw} kW × {duration} dk × ~85% verim)
            </span>
          </div>

          {/* Tahmini ücret */}
          {stop.cost_try != null && stop.cost_try > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-900">
              💰 Tahmini ücret:{' '}
              <span className="font-bold text-base">
                {(
                  ((duration / 60) * stop.power_kw * 0.85) /
                  Math.max(stop.energy_kwh ?? 1, 0.01)
                  * stop.cost_try
                ).toFixed(0)}{' '}
                ₺
              </span>
              {stop.operator && (
                <span className="ml-2 text-amber-700">— {stop.operator} tarifesi</span>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 border-t border-slate-200 bg-slate-50 px-5 py-3">
          {isEditing ? (
            <button
              onClick={onCancel}
              className="rounded-md border border-red-200 bg-white px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
            >
              ✕ Rezervasyonu İptal Et
            </button>
          ) : (
            <button
              onClick={onClose}
              className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100"
            >
              Vazgeç
            </button>
          )}
          <button
            onClick={handleConfirm}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-emerald-500"
          >
            {isEditing ? 'Güncelle' : 'Rezerve Et'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="text-sm font-bold text-slate-900">{value}</div>
    </div>
  )
}
