import type { RouteHistoryEntry } from '../hooks/useRouteHistory'

interface Props {
  entries: RouteHistoryEntry[]
  onSelect: (entry: RouteHistoryEntry) => void
  onRemove: (id: string) => void
  onClearAll: () => void
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) {
    return d.toLocaleTimeString('tr-TR', {
      hour: '2-digit',
      minute: '2-digit',
    })
  }
  return d.toLocaleDateString('tr-TR', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function RouteHistoryPanel({
  entries,
  onSelect,
  onRemove,
  onClearAll,
}: Props) {
  if (entries.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/60 p-3 text-center text-[11px] text-slate-500">
        Henüz kayıtlı rota yok.
        <br />
        Optimize ettiğin rotalar burada birikir (max 10).
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-slate-500">
        <span>{entries.length} rota</span>
        <button
          type="button"
          onClick={onClearAll}
          className="text-red-500 hover:text-red-700"
        >
          Tümünü temizle
        </button>
      </div>

      <ul className="flex flex-col gap-1.5">
        {entries.map((e) => (
          <li
            key={e.id}
            className="group flex items-center gap-2 rounded-lg border border-slate-200 bg-white/70 p-2 backdrop-blur transition hover:border-indigo-300 hover:bg-indigo-50/50"
          >
            <button
              type="button"
              onClick={() => onSelect(e)}
              className="flex min-w-0 flex-1 flex-col text-left"
            >
              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-900">
                <span className="truncate">{e.start.name}</span>
                <span className="text-slate-400">→</span>
                <span className="truncate">{e.end.name}</span>
              </div>
              <div className="text-[10px] text-slate-500">
                {e.vehicleName ?? e.vehicleId} · %{e.initialSocPct.toFixed(0)}
                {e.totalDistanceKm
                  ? ` · ${e.totalDistanceKm.toFixed(0)} km`
                  : ''}
                {e.totalCostTry != null && e.totalCostTry > 0
                  ? ` · ${e.totalCostTry.toFixed(0)}₺`
                  : ''}
              </div>
              <div className="text-[9px] text-slate-400">{formatTime(e.timestamp)}</div>
            </button>
            <button
              type="button"
              onClick={() => onRemove(e.id)}
              className="rounded p-1 text-slate-300 opacity-0 transition hover:text-red-500 group-hover:opacity-100"
              aria-label="Sil"
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
