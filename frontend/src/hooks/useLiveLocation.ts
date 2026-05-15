import { useEffect, useRef, useState } from 'react'

export interface LivePosition {
  lat: number
  lon: number
  heading: number
  speedKmh: number
  accuracyM: number
  timestamp: number
}

export interface UseLiveLocationOptions {
  enabled: boolean
  enableHighAccuracy?: boolean
  minMoveMeters?: number
}

function haversineMeters(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const R = 6371000
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(a))
}

function bearingDeg(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const toRad = (d: number) => (d * Math.PI) / 180
  const toDeg = (r: number) => (r * 180) / Math.PI
  const dLon = toRad(lon2 - lon1)
  const y = Math.sin(dLon) * Math.cos(toRad(lat2))
  const x =
    Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
    Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(dLon)
  return (toDeg(Math.atan2(y, x)) + 360) % 360
}

export function useLiveLocation({
  enabled,
  enableHighAccuracy = true,
  minMoveMeters = 3,
}: UseLiveLocationOptions) {
  const [pos, setPos] = useState<LivePosition | null>(null)
  const [error, setError] = useState<string | null>(null)
  const lastRef = useRef<LivePosition | null>(null)

  useEffect(() => {
    if (!enabled) {
      lastRef.current = null
      setPos(null)
      setError(null)
      return
    }
    if (!navigator.geolocation) {
      setError('Tarayıcı konum servisini desteklemiyor.')
      return
    }

    const watchId = navigator.geolocation.watchPosition(
      (p) => {
        const prev = lastRef.current
        const next: LivePosition = {
          lat: p.coords.latitude,
          lon: p.coords.longitude,
          heading:
            p.coords.heading != null && Number.isFinite(p.coords.heading)
              ? p.coords.heading
              : prev
                ? bearingDeg(prev.lat, prev.lon, p.coords.latitude, p.coords.longitude)
                : 0,
          speedKmh:
            p.coords.speed != null && Number.isFinite(p.coords.speed)
              ? p.coords.speed * 3.6
              : 0,
          accuracyM: p.coords.accuracy ?? 0,
          timestamp: p.timestamp,
        }
        if (prev) {
          const moved = haversineMeters(prev.lat, prev.lon, next.lat, next.lon)
          if (moved < minMoveMeters) return
        }
        lastRef.current = next
        setPos(next)
        setError(null)
      },
      (err) => setError(err.message || 'GPS hatası'),
      { enableHighAccuracy, maximumAge: 1000, timeout: 10000 },
    )
    return () => navigator.geolocation.clearWatch(watchId)
  }, [enabled, enableHighAccuracy, minMoveMeters])

  return { pos, error }
}
