import { useEffect, useState } from 'react'
import type { GeocodeResultItem } from '../services/schemas'

export interface RouteHistoryEntry {
  id: string
  timestamp: number
  vehicleId: string
  vehicleName?: string
  start: GeocodeResultItem
  end: GeocodeResultItem
  initialSocPct: number
  targetArrivalSocPct?: number | null
  totalDistanceKm?: number
  totalCostTry?: number
}

const STORAGE_KEY = 'evro:route-history'
const MAX_ENTRIES = 10

function loadFromStorage(): RouteHistoryEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(
        (e): e is RouteHistoryEntry =>
          !!e &&
          typeof e.id === 'string' &&
          typeof e.timestamp === 'number' &&
          !!e.start &&
          !!e.end,
      )
      .slice(0, MAX_ENTRIES)
  } catch {
    return []
  }
}

function saveToStorage(entries: RouteHistoryEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
  } catch {
    // Quota dolu olabilir; sessizce geç.
  }
}

export function useRouteHistory() {
  const [entries, setEntries] = useState<RouteHistoryEntry[]>(() =>
    loadFromStorage(),
  )

  useEffect(() => {
    saveToStorage(entries)
  }, [entries])

  const addEntry = (entry: Omit<RouteHistoryEntry, 'id' | 'timestamp'>) => {
    const id =
      'rh-' +
      Date.now().toString(36) +
      Math.random().toString(36).slice(2, 6)
    const newEntry: RouteHistoryEntry = {
      ...entry,
      id,
      timestamp: Date.now(),
    }
    setEntries((prev) => {
      // Aynı başlangıç+bitiş+araç kombinasyonu varsa eski kaydı çıkar
      const filtered = prev.filter(
        (e) =>
          !(
            e.vehicleId === entry.vehicleId &&
            Math.abs(e.start.lat - entry.start.lat) < 0.0001 &&
            Math.abs(e.start.lon - entry.start.lon) < 0.0001 &&
            Math.abs(e.end.lat - entry.end.lat) < 0.0001 &&
            Math.abs(e.end.lon - entry.end.lon) < 0.0001
          ),
      )
      return [newEntry, ...filtered].slice(0, MAX_ENTRIES)
    })
  }

  const removeEntry = (id: string) => {
    setEntries((prev) => prev.filter((e) => e.id !== id))
  }

  const clearAll = () => {
    setEntries([])
  }

  return { entries, addEntry, removeEntry, clearAll }
}
