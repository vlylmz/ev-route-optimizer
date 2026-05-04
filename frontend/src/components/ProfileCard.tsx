import type {
  ProfileCard as ProfileCardType,
  RecommendedStop,
} from '../services/schemas'
import type { Reservation } from './ReservationDialog'

interface Props {
  card: ProfileCardType
  recommended?: boolean
  active?: boolean
  onSelect?: () => void
  reservations?: Record<string, Reservation>
  onReserve?: (stop: RecommendedStop) => void
}

const STRATEGY_EMOJI: Record<string, string> = {
  fast: '⚡',
  efficient: '🌿',
  balanced: '⚖️',
}

function fmt(value: number | null | undefined, suffix: string, digits = 1) {
  if (value == null) return '—'
  return `${value.toFixed(digits)} ${suffix}`
}

function stopKey(strategyKey: string, idx: number): string {
  return `${strategyKey}::${idx}`
}

export function ProfileCard({
  card,
  recommended,
  active,
  onSelect,
  reservations = {},
  onReserve,
}: Props) {
  const border = active
    ? 'border-emerald-500 ring-2 ring-emerald-300 bg-emerald-50/80'
    : recommended
    ? 'border-indigo-500 ring-2 ring-indigo-200'
    : 'border-slate-200 hover:border-indigo-300'

  const stops = card.recommended_stops ?? []

  const handleHeaderClick = () => {
    if (onSelect) onSelect()
  }

  return (
    <article
      data-testid={`profile-card-${card.key}`}
      className={`relative flex flex-col gap-3 rounded-xl border bg-white/85 p-4 shadow-sm backdrop-blur transition ${border}`}
    >
      {active && (
        <span className="absolute -top-2 left-3 rounded-full bg-emerald-600 px-2 py-0.5 text-[10px] font-semibold text-white shadow">
          ✓ Haritada
        </span>
      )}
      {recommended && !active && (
        <span className="absolute -top-2 right-3 rounded-full bg-indigo-600 px-2 py-0.5 text-[10px] font-semibold text-white shadow">
          Önerilen
        </span>
      )}

      <button
        type="button"
        onClick={handleHeaderClick}
        disabled={!onSelect}
        className="flex items-center gap-2 text-left disabled:cursor-default"
      >
        <span className="text-xl">{STRATEGY_EMOJI[card.key] ?? '•'}</span>
        <div className="flex-1">
          <h3 className="text-base font-semibold text-slate-900">
            {card.label}
          </h3>
          <p className="text-xs text-slate-500">
            {card.feasible ? 'Uygulanabilir' : 'Uygun değil'}
            {onSelect && !active && (
              <span className="ml-1 text-indigo-500">— seçmek için tıkla</span>
            )}
          </p>
        </div>
      </button>

      <dl className="grid grid-cols-3 gap-2 text-sm">
        <Stat label="Enerji" value={fmt(card.total_energy_kwh, 'kWh', 1)} />
        <Stat label="Süre" value={fmt(card.total_trip_minutes, 'dk', 0)} />
        <Stat label="Şarj" value={fmt(card.charging_minutes, 'dk', 0)} />
        <Stat
          label="Durak"
          value={card.stop_count != null ? String(card.stop_count) : '—'}
        />
        <Stat label="Varış" value={fmt(card.final_soc_pct, '%', 0)} />
        <Stat label="Kaynak" value={card.used_ml ? 'ML' : 'Formül'} />
      </dl>

      {/* Rezervasyon yapılabilir duraklar */}
      {stops.length > 0 && onReserve && (
        <div className="flex flex-col gap-1.5 border-t border-slate-200 pt-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            🔌 Şarj Durakları
          </div>
          {stops.map((s, idx) => {
            const key = stopKey(card.key, idx)
            const reserved = reservations[key]
            return (
              <button
                key={key}
                type="button"
                onClick={() => onReserve(s)}
                className={
                  'flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-left text-xs transition ' +
                  (reserved
                    ? 'border-emerald-300 bg-emerald-50/80 hover:bg-emerald-100/80'
                    : 'border-slate-200 bg-white/70 hover:bg-indigo-50')
                }
              >
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-semibold text-slate-900">
                    {s.name}
                  </span>
                  <span className="text-[10px] text-slate-500">
                    {s.distance_along_route_km.toFixed(0)} km · {s.power_kw} kW
                    · ~{s.charge_minutes.toFixed(0)} dk
                  </span>
                </div>
                {reserved ? (
                  <span className="rounded bg-emerald-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                    ✓ {reserved.startTime}
                  </span>
                ) : (
                  <span className="text-[10px] font-medium text-indigo-600">
                    Rezerve et →
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}
    </article>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-50/80 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="text-sm font-semibold text-slate-900">{value}</div>
    </div>
  )
}
