import { useEffect, useRef } from 'react'
import type { LivePosition } from './useLiveLocation'
import type { OptimizeRequest } from '../services/schemas'

export interface DynamicReroutingOptions {
  enabled: boolean
  livePos: LivePosition | null
  /** Son optimize isteginin tum parametreleri; start canli konumla override edilir. */
  baseRequest: OptimizeRequest | null
  /** Mevcut SoC (% ); verilmezse baseRequest.initial_soc_pct kullanilir. */
  currentSocPct?: number | null
  /** Esik km (varsayilan 30). */
  triggerEveryKm?: number
  /** Yeniden rotalama tetiklenince cagrilacak action. */
  onReroute: (req: OptimizeRequest) => void
  /** Iki tetikleme arasi minimum hiz (km/s); araç park halindeyse trigger atilir. */
  minSpeedKmh?: number
  /** Esik tetikleme sonrasi cooldown (ms). Backend tamamlanmadan ust uste rotalanmasin. */
  cooldownMs?: number
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

/**
 * Her N km'de bir mevcut rotayı arka planda yeniden hesaplar.
 *
 * Mantık:
 * 1) Hook etkinleştirildiğinde mevcut canlı konum 'anchor' olarak alınır.
 * 2) Her pozisyon güncellemesinde anchor'dan haversine mesafe ölçülür.
 * 3) Mesafe `triggerEveryKm` aşınca onReroute çağrılır, anchor güncellenir,
 *    cooldown başlar (varsayılan 5 sn) — backend yanıtı dönerken tekrar
 *    tetiklenmesini engeller.
 */
export function useDynamicRerouting({
  enabled,
  livePos,
  baseRequest,
  currentSocPct,
  triggerEveryKm = 30,
  minSpeedKmh = 5,
  cooldownMs = 5000,
  onReroute,
}: DynamicReroutingOptions) {
  const anchorRef = useRef<{ lat: number; lon: number } | null>(null)
  const inFlightRef = useRef(false)
  const cooldownTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Hook kapatildiginda / pozisyon ilk geldiğinde anchor'u resetle
  useEffect(() => {
    if (!enabled) {
      anchorRef.current = null
      inFlightRef.current = false
      if (cooldownTimerRef.current) {
        clearTimeout(cooldownTimerRef.current)
        cooldownTimerRef.current = null
      }
      return
    }
    if (livePos && !anchorRef.current) {
      anchorRef.current = { lat: livePos.lat, lon: livePos.lon }
    }
  }, [enabled, livePos])

  // Unmount'ta bekleyen cooldown timer'i temizle.
  useEffect(() => {
    return () => {
      if (cooldownTimerRef.current) {
        clearTimeout(cooldownTimerRef.current)
        cooldownTimerRef.current = null
      }
    }
  }, [])

  // Konum güncellendikçe eşik kontrolü
  useEffect(() => {
    if (!enabled || !livePos || !baseRequest) return
    if (inFlightRef.current) return
    const anchor = anchorRef.current
    if (!anchor) return

    if (livePos.speedKmh < minSpeedKmh) return // park / dur-kalk

    const traveled = haversineKm(
      anchor.lat,
      anchor.lon,
      livePos.lat,
      livePos.lon,
    )
    if (traveled < triggerEveryKm) return

    inFlightRef.current = true
    const newReq: OptimizeRequest = {
      ...baseRequest,
      start: { lat: livePos.lat, lon: livePos.lon },
      initial_soc_pct:
        currentSocPct != null
          ? Math.max(0, Math.min(100, currentSocPct))
          : baseRequest.initial_soc_pct,
    }
    onReroute(newReq)
    anchorRef.current = { lat: livePos.lat, lon: livePos.lon }

    if (cooldownTimerRef.current) clearTimeout(cooldownTimerRef.current)
    cooldownTimerRef.current = setTimeout(() => {
      inFlightRef.current = false
      cooldownTimerRef.current = null
    }, cooldownMs)
  }, [
    enabled,
    livePos,
    baseRequest,
    currentSocPct,
    triggerEveryKm,
    minSpeedKmh,
    cooldownMs,
    onReroute,
  ])
}
