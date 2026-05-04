import type { ProfileCard as ProfileCardType } from '../services/schemas'

interface Props {
  card: ProfileCardType
  recommended?: boolean
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

export function ProfileCard({ card, recommended }: Props) {
  const border = recommended
    ? 'border-indigo-500 ring-2 ring-indigo-200'
    : 'border-slate-200'

  return (
    <article
      data-testid={`profile-card-${card.key}`}
      className={`relative flex flex-col gap-3 rounded-xl border bg-white p-5 shadow-sm ${border}`}
    >
      {recommended && (
        <span className="absolute -top-2 right-3 rounded-full bg-indigo-600 px-2 py-0.5 text-xs font-semibold text-white shadow">
          Önerilen
        </span>
      )}

      <header className="flex items-center gap-2">
        <span className="text-xl">{STRATEGY_EMOJI[card.key] ?? '•'}</span>
        <div>
          <h3 className="text-base font-semibold text-slate-900">
            {card.label}
          </h3>
          <p className="text-xs text-slate-500">
            {card.feasible ? 'Uygulanabilir' : 'Uygun değil'}
          </p>
        </div>
      </header>

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
          label="Kaynak"
          value={card.used_ml ? 'ML' : 'Formül'}
        />
      </dl>
    </article>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="text-sm font-semibold text-slate-900">{value}</div>
    </div>
  )
}
