import { useEffect, useRef, useState } from 'react'
import { getGeocode } from '../services/api'
import type { GeocodeResultItem } from '../services/schemas'

interface Props {
  label: string
  placeholder?: string
  value: GeocodeResultItem | null
  onChange: (value: GeocodeResultItem | null) => void
  disabled?: boolean
}

/**
 * Yer adı (Ankara, Çankaya, Beşiktaş…) için Nominatim destekli
 * arama kutusu. 350ms debounce, ESC ile kapatma, click-outside.
 */
export function LocationSearchInput({
  label,
  placeholder = 'Şehir veya konum ara…',
  value,
  onChange,
  disabled,
}: Props) {
  const [text, setText] = useState<string>(value?.name ?? '')
  const [results, setResults] = useState<GeocodeResultItem[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const debounceRef = useRef<number | null>(null)

  // Dış prop değişirse text'i senkronize et
  useEffect(() => {
    setText(value?.name ?? '')
  }, [value])

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current)
    }

    const trimmed = text.trim()
    // Seçili olanın adı zaten yazılıysa arama yapma
    if (!trimmed || trimmed.length < 2 || trimmed === value?.name) {
      setResults([])
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)

    debounceRef.current = window.setTimeout(async () => {
      try {
        const data = await getGeocode(trimmed, 6)
        setResults(data.results)
        setOpen(true)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Arama hatası')
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 350)

    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text])

  // Click outside
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const handleSelect = (item: GeocodeResultItem) => {
    onChange(item)
    setText(item.name)
    setResults([])
    setOpen(false)
  }

  const handleClear = () => {
    onChange(null)
    setText('')
    setResults([])
  }

  return (
    <div className="relative flex flex-col gap-1" ref={containerRef}>
      <label className="text-xs font-medium text-slate-600">{label}</label>
      <div className="relative">
        <input
          type="text"
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            // Kullanıcı yazıyorsa seçimi temizle, yeni arama tetiklensin
            if (value && e.target.value !== value.name) {
              onChange(null)
            }
          }}
          onFocus={() => results.length > 0 && setOpen(true)}
          onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
          placeholder={placeholder}
          disabled={disabled}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 pr-9 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:bg-slate-100"
        />
        {value && (
          <button
            type="button"
            onClick={handleClear}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded text-xs text-slate-400 hover:text-slate-700"
            aria-label="Temizle"
          >
            ✕
          </button>
        )}
      </div>

      {/* Durum etiketleri */}
      {loading && (
        <span className="text-[10px] text-slate-400">aranıyor…</span>
      )}
      {error && (
        <span className="text-[10px] text-red-500">{error}</span>
      )}
      {value && !open && (
        <span className="truncate text-[10px] text-emerald-600">
          ✓ {value.lat.toFixed(4)}, {value.lon.toFixed(4)}
        </span>
      )}

      {/* Dropdown */}
      {open && results.length > 0 && (
        <ul className="absolute left-0 right-0 top-full z-30 mt-1 max-h-72 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-xl">
          {results.map((r, idx) => (
            <li key={`${r.lat}-${r.lon}-${idx}`}>
              <button
                type="button"
                onClick={() => handleSelect(r)}
                className="flex w-full flex-col items-start gap-0.5 border-b border-slate-100 px-3 py-2 text-left text-xs hover:bg-indigo-50 last:border-0"
              >
                <span className="font-semibold text-slate-900">{r.name}</span>
                <span className="line-clamp-2 text-[10px] text-slate-500">
                  {r.display_name}
                </span>
                {r.type && (
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-slate-500">
                    {r.type}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
