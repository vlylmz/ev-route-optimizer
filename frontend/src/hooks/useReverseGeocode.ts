import { useEffect, useRef, useState } from 'react'
import { getReverseGeocode } from '../services/api'
import type { GeocodeResultItem } from '../services/schemas'

interface UseReverseGeocodeOptions {
  enabled: boolean
  lat: number | null | undefined
  lon: number | null | undefined
  /** Yeniden sorgulama icin min km hareketi. */
  minMoveKm?: number
  /** Iki sorgu arasi min bekleme (ms). Nominatim 1/sn rate-limit'ine uyumlu. */
  minIntervalMs?: number
}

function haversineKm(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const R = 6371
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(a))
}

export function useReverseGeocode({
  enabled,
  lat,
  lon,
  minMoveKm = 0.5,
  minIntervalMs = 5000,
}: UseReverseGeocodeOptions) {
  const [data, setData] = useState<GeocodeResultItem | null>(null)
  const [error, setError] = useState<string | null>(null)
  const lastFetchedRef = useRef<{
    lat: number
    lon: number
    ts: number
  } | null>(null)
  const inFlightRef = useRef(false)

  useEffect(() => {
    if (!enabled || lat == null || lon == null) return
    const last = lastFetchedRef.current
    const now = Date.now()
    if (last) {
      const moved = haversineKm(last.lat, last.lon, lat, lon)
      const elapsed = now - last.ts
      if (moved < minMoveKm || elapsed < minIntervalMs) return
    }
    if (inFlightRef.current) return
    inFlightRef.current = true
    lastFetchedRef.current = { lat, lon, ts: now }

    getReverseGeocode(lat, lon)
      .then((res) => {
        setData(res)
        setError(null)
      })
      .catch((err: unknown) => {
        const message =
          err instanceof Error ? err.message : 'Reverse geocode hatası'
        setError(message)
      })
      .finally(() => {
        inFlightRef.current = false
      })
  }, [enabled, lat, lon, minMoveKm, minIntervalMs])

  // Sim/canli konum kapaninca state'i temizle
  useEffect(() => {
    if (!enabled) {
      setData(null)
      setError(null)
      lastFetchedRef.current = null
    }
  }, [enabled])

  return { data, error }
}
