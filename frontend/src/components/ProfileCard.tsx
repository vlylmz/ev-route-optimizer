import { Zap, Leaf, Scale, Plug } from 'lucide-react'
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

const STRATEGY_ICON: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  fast: Zap,
  efficient: Leaf,
  balanced: Scale,
}

const STRATEGY_TONE: Record<string, string> = {
  fast: 'text-amber-500',
  efficient: 'text-emerald-500',
  balanced: 'text-indigo-500',
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
    ? 'border-indigo-600 ring-4 ring-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-violet-50 shadow-md'
    : 'border-slate-200 hover:border-indigo-300 opacity-70 hover:opacity-100'

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
        <span className="absolute -top-2 left-3 inline-flex items-center gap-1 rounded-full bg-indigo-600 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white shadow-md">
          <span className="h-1.5 w-1.5 rounded-full bg-white" />
          Aktif
        </span>
      )}
      {recommended && !active && (
        <span className="absolute -top-2 right-3 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
          Önerilen
        </span>
      )}

      <button
        type="button"
        onClick={handleHeaderClick}
        disabled={!onSelect}
        className="flex items-center gap-2 text-left disabled:cursor-default"
      >
        {(() => {
          const Icon = STRATEGY_ICON[card.key]
          return Icon ? (
            <Icon
              size={20}
              className={STRATEGY_TONE[card.key] ?? 'text-slate-500'}
            />
          ) : null
        })()}
        <div className="flex-1">
          <h3 className="flex items-center gap-1.5 text-base font-semibold text-slate-900">
            <span>{card.label}</span>
            <span
              className={
                'rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ' +
                (card.used_ml
                  ? 'bg-indigo-100 text-indigo-700'
                  : 'bg-slate-100 text-slate-600')
              }
            >
              {card.used_ml
                ? `ML${card.model_version ? ` · ${card.model_version}` : ''}`
                : 'Formül'}
            </span>
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
        <Stat
          label="Maliyet"
          value={
            card.total_cost_try > 0
              ? `${card.total_cost_try.toFixed(0)} ₺`
              : '—'
          }
        />
      </dl>

      {/* Rezervasyon yapılabilir duraklar */}
      {stops.length > 0 && onReserve && (
        <div className="flex flex-col gap-1.5 border-t border-slate-200 pt-3">
          <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            <Plug size={11} />
            <span>Şarj Durakları</span>
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
                    {s.operator && ` · ${s.operator}`}
                  </span>
                  {s.cost_try > 0 && (
                    <span className="text-[10px] font-semibold text-amber-700">
                      💰 {s.energy_kwh.toFixed(1)} kWh · {s.cost_try.toFixed(0)} ₺
                    </span>
                  )}
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
    <div className="rounded-lg bg-slate-50/80 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="text-sm font-semibold text-slate-900">{value}</div>
    </div>
  )
}
