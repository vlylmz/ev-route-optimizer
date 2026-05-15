import { useEffect, useMemo, useRef, useState } from 'react'
import Map, {
  Layer,
  Marker,
  NavigationControl,
  Popup,
  Source,
  type MapRef,
} from 'react-map-gl/maplibre'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useQuery } from '@tanstack/react-query'
import { postChargingCurve } from '../services/api'
import { bearingDeg, haversineKm } from '../services/geo'
import { ChargingCurveChart } from './ChargingCurveChart'

interface Station {
  ocm_id?: number
  name?: string
  latitude?: number
  longitude?: number
  power_kw?: number
  distance_from_route_km?: number
}

interface SpeedLimitSegment {
  start_index: number
  end_index: number
  maxspeed_kmh?: number | null
  highway?: string | null
}

interface HighlightedStop {
  name: string
  // Bu stop için yaklaşık koordinat: rota geometrisinden bulacağız
  distance_along_route_km: number
  power_kw?: number
  charge_minutes?: number
  arrival_soc_percent?: number
  target_soc_percent?: number
  reserved?: boolean
}

interface Props {
  geometry: number[][] // [[lat, lon], ...]
  // Backend tarafindan hesaplanan kumulatif mesafe (km). Yoksa client-side
  // haversine sum'a duser (geriye uyumluluk).
  cumulativeDistancesKm?: number[]
  stations?: Station[]
  start?: { lat: number; lon: number }
  end?: { lat: number; lon: number }
  navigationMode?: boolean
  speedLimits?: SpeedLimitSegment[]
  highlightedStops?: HighlightedStop[]
  vehicleId?: string
  initialSocPct?: number
  usableBatteryKwh?: number
  // Enerji-temelli sim SOC hesabi icin gerekli.
  idealConsumptionWhKm?: number
  // Backend'den gelen baseline kWh/km hesabi icin: total_energy / total_distance.
  totalEnergyKwh?: number
  // Canli konum (nav-mode bagimsiz). useLiveLocation hook'u doldurur.
  liveLocation?: { lat: number; lon: number; heading: number } | null
  liveLocationVisible?: boolean
  // Sim aktifken pozisyonu App'e ilet (useDynamicRerouting bunu kullanir).
  onSimPositionUpdate?: (
    pos: { lat: number; lon: number; heading: number; speedKmh: number } | null,
  ) => void
  // Kullanici sim hizini degistirince App'e haber ver (reroute trigger icin).
  onSimVehicleSpeedChange?: (kmh: number) => void
  // Disaridan ref baglanarak haritanin canvas'i export icin yakalanir.
  mapRef?: React.RefObject<MapRef | null>
}

const MAP_STYLE = 'https://tiles.openfreemap.org/styles/liberty'
const ANKARA_CENTER = { lng: 32.85, lat: 39.92, zoom: 6 }

export function MapView({
  geometry,
  cumulativeDistancesKm,
  stations = [],
  start,
  end,
  navigationMode = false,
  speedLimits,
  highlightedStops = [],
  vehicleId,
  initialSocPct,
  usableBatteryKwh,
  idealConsumptionWhKm,
  totalEnergyKwh,
  liveLocation,
  liveLocationVisible = false,
  onSimPositionUpdate,
  onSimVehicleSpeedChange,
  mapRef: externalMapRef,
}: Props) {
  const internalMapRef = useRef<MapRef | null>(null)
  const mapRef = externalMapRef ?? internalMapRef
  const [pos, setPos] = useState<{ lat: number; lon: number } | null>(null)
  const [heading, setHeading] = useState<number>(0)
  const [followMode, setFollowMode] = useState<boolean>(true)
  const [pitch, setPitch] = useState<number>(85)
  const [gpsError, setGpsError] = useState<string | null>(null)
  const [activeStation, setActiveStation] = useState<number | null>(null)
  const [currentSegmentIdx, setCurrentSegmentIdx] = useState<number | null>(
    null,
  )

  // Simülasyon: rotada otomatik ilerleyen sanal araç
  const [simEnabled, setSimEnabled] = useState<boolean>(false)
  const [simRunning, setSimRunning] = useState<boolean>(false)
  // Aracin "gercek" hizi (km/h). Enerji tuketimi ve hiz limiti karsilastirmasi
  // bunun uzerinden yapilir. Backend energy_model.IDEAL_SPEED_KMH=90 ile uyumlu.
  const [simVehicleSpeedKmh, setSimVehicleSpeedKmh] = useState<number>(90)
  // Demo hiz carpani: sim saatinin gercek saate gore ne kadar hizli aktigi.
  // 1x = gercek zaman; 16x = 1sn gercek = 16sn sim.
  const [simTimeMul, setSimTimeMul] = useState<number>(8)
  const [simKm, setSimKm] = useState<number>(0) // şu anki kümülatif km
  const [simArrived, setSimArrived] = useState<boolean>(false)
  // Sim'de durağa ulaşıldığında "şarj olunuyor" paneli için durum
  const [chargingStopIdx, setChargingStopIdx] = useState<number | null>(null)
  const [completedStops, setCompletedStops] = useState<Set<number>>(new Set())

  const hasRoute = geometry.length > 1

  // GeoJSON polyline (lon, lat) — tek parça (sim kapalıyken)
  const routeGeoJson = useMemo(() => {
    if (!hasRoute) return null
    return {
      type: 'Feature' as const,
      geometry: {
        type: 'LineString' as const,
        coordinates: geometry.map(([lat, lon]) => [lon, lat]),
      },
      properties: {},
    }
  }, [geometry, hasRoute])

  // Rota geometrisinin kumulatif mesafe profili (km).
  // Backend RouteResponse.cumulative_distances dolu ise onu kullan; aksi halde
  // client-side haversine sum (eski rotalar / fallback).
  const cumulativeDistances = useMemo(() => {
    if (!hasRoute) return [] as number[]
    if (
      cumulativeDistancesKm &&
      cumulativeDistancesKm.length === geometry.length
    ) {
      return cumulativeDistancesKm
    }
    const arr: number[] = [0]
    for (let i = 1; i < geometry.length; i++) {
      const d = haversineKm(
        geometry[i - 1][0],
        geometry[i - 1][1],
        geometry[i][0],
        geometry[i][1],
      )
      arr.push(arr[i - 1] + d)
    }
    return arr
  }, [geometry, hasRoute, cumulativeDistancesKm])

  // Sim modunda rota'yı simKm'de "traveled" ve "remaining" olarak böl
  const splitRoute = useMemo(() => {
    if (!hasRoute || !simEnabled) return null
    const totalKm = cumulativeDistances[cumulativeDistances.length - 1] || 0
    if (totalKm <= 0) return null
    const clamped = Math.max(0, Math.min(simKm, totalKm))

    // Bölme noktasının segment indeksini bul
    let idx = 0
    for (let i = 0; i < cumulativeDistances.length - 1; i++) {
      if (cumulativeDistances[i + 1] >= clamped) {
        idx = i
        break
      }
      idx = i + 1
    }
    const segStart = cumulativeDistances[idx]
    const segEnd = cumulativeDistances[Math.min(idx + 1, geometry.length - 1)]
    const t = segEnd > segStart ? (clamped - segStart) / (segEnd - segStart) : 0
    const splitLat =
      geometry[idx][0] +
      (geometry[Math.min(idx + 1, geometry.length - 1)][0] - geometry[idx][0]) * t
    const splitLon =
      geometry[idx][1] +
      (geometry[Math.min(idx + 1, geometry.length - 1)][1] - geometry[idx][1]) * t

    // Traveled: 0..idx + ara split noktası
    const traveledCoords: [number, number][] = geometry
      .slice(0, idx + 1)
      .map(([lat, lon]) => [lon, lat])
    traveledCoords.push([splitLon, splitLat])

    // Remaining: split noktası + idx+1..end
    const remainingCoords: [number, number][] = [[splitLon, splitLat]]
    for (let i = idx + 1; i < geometry.length; i++) {
      remainingCoords.push([geometry[i][1], geometry[i][0]])
    }

    return {
      traveled: {
        type: 'Feature' as const,
        geometry: { type: 'LineString' as const, coordinates: traveledCoords },
        properties: {},
      },
      remaining: {
        type: 'Feature' as const,
        geometry: { type: 'LineString' as const, coordinates: remainingCoords },
        properties: {},
      },
    }
  }, [hasRoute, simEnabled, simKm, cumulativeDistances, geometry])

  // Highlighted stop'ları rota üzerinde mesafeye göre yerleştir
  const highlightedPositions = useMemo(() => {
    if (!hasRoute || highlightedStops.length === 0) return []
    return highlightedStops
      .map((stop) => {
        // Verilen mesafeye en yakın geometry indeksini bul
        let bestIdx = 0
        let bestDiff = Infinity
        for (let i = 0; i < cumulativeDistances.length; i++) {
          const diff = Math.abs(cumulativeDistances[i] - stop.distance_along_route_km)
          if (diff < bestDiff) {
            bestDiff = diff
            bestIdx = i
          }
        }
        return {
          ...stop,
          lat: geometry[bestIdx][0],
          lon: geometry[bestIdx][1],
        }
      })
  }, [highlightedStops, cumulativeDistances, geometry, hasRoute])

  // Initial view: rotanın bbox'ı ya da Ankara
  const initialView = useMemo(() => {
    if (start) return { lng: start.lon, lat: start.lat, zoom: 7 }
    if (hasRoute) return { lng: geometry[0][1], lat: geometry[0][0], zoom: 7 }
    return ANKARA_CENTER
  }, [start, geometry, hasRoute])

  // Rota değiştiğinde haritayı bbox'a oturt
  useEffect(() => {
    if (!hasRoute || !mapRef.current) return
    const map = mapRef.current.getMap()
    let minLng = Infinity
    let minLat = Infinity
    let maxLng = -Infinity
    let maxLat = -Infinity
    for (const [lat, lon] of geometry) {
      if (lon < minLng) minLng = lon
      if (lat < minLat) minLat = lat
      if (lon > maxLng) maxLng = lon
      if (lat > maxLat) maxLat = lat
    }
    if (Number.isFinite(minLng)) {
      map.fitBounds(
        [
          [minLng, minLat],
          [maxLng, maxLat],
        ],
        {
          padding: 80,
          duration: 800,
          pitch: navigationMode ? pitch : 30,
          bearing: 0,
        },
      )
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometry])

  // Navigation moduna geçince GPS başlat / kapatınca durdur
  // Simülasyon açıksa GPS kullanma — pozisyonu sim loop yönetir.
  useEffect(() => {
    if (!navigationMode || simEnabled) {
      if (!simEnabled) setPos(null)
      setGpsError(null)
      return
    }
    if (!navigator.geolocation) {
      setGpsError('Tarayıcı konum servisini desteklemiyor.')
      return
    }
    const watchId = navigator.geolocation.watchPosition(
      (p) => {
        const next = { lat: p.coords.latitude, lon: p.coords.longitude }
        setPos((prev) => {
          if (prev) {
            const moved = haversineKm(prev.lat, prev.lon, next.lat, next.lon)
            if (moved > 0.005) {
              if (
                p.coords.heading != null &&
                !Number.isNaN(p.coords.heading)
              ) {
                setHeading(p.coords.heading)
              } else {
                setHeading(
                  bearingDeg(prev.lat, prev.lon, next.lat, next.lon),
                )
              }
            }
          } else if (
            p.coords.heading != null &&
            !Number.isNaN(p.coords.heading)
          ) {
            setHeading(p.coords.heading)
          }
          return next
        })
        setGpsError(null)
      },
      (err) => setGpsError(err.message || 'GPS hatası'),
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 10000 },
    )
    return () => navigator.geolocation.clearWatch(watchId)
  }, [navigationMode, simEnabled])

  // Simülasyon animasyon döngüsü
  // simEnabled açıkken simKm sürekli artar, pozisyon ve heading geometriden
  // hesaplanarak set edilir.
  useEffect(() => {
    if (!navigationMode || !simEnabled || !hasRoute) return

    const totalKm = cumulativeDistances[cumulativeDistances.length - 1] || 0
    if (totalKm <= 0) return

    // Simülasyon başladığında varış flag'ini sıfırla
    if (simKm === 0) setSimArrived(false)

    // Pozisyonu mevcut simKm'e göre yerleştir (running olmasa bile)
    const placeAt = (km: number) => {
      const clamped = Math.max(0, Math.min(km, totalKm))
      // Hangi segmentteyiz?
      let idx = 0
      for (let i = 0; i < cumulativeDistances.length - 1; i++) {
        if (cumulativeDistances[i + 1] >= clamped) {
          idx = i
          break
        }
        idx = i + 1
      }
      const segStart = cumulativeDistances[idx]
      const segEnd = cumulativeDistances[Math.min(idx + 1, geometry.length - 1)]
      const t = segEnd > segStart ? (clamped - segStart) / (segEnd - segStart) : 0
      const lat =
        geometry[idx][0] +
        (geometry[Math.min(idx + 1, geometry.length - 1)][0] - geometry[idx][0]) * t
      const lon =
        geometry[idx][1] +
        (geometry[Math.min(idx + 1, geometry.length - 1)][1] - geometry[idx][1]) * t

      setPos({ lat, lon })
      // Heading: bir sonraki noktaya göre
      const ahead = Math.min(idx + 1, geometry.length - 1)
      if (ahead !== idx) {
        setHeading(
          bearingDeg(geometry[idx][0], geometry[idx][1], geometry[ahead][0], geometry[ahead][1]),
        )
      }
    }

    // İlk yerleştirme
    placeAt(simKm)

    if (!simRunning) return

    // rAF tabanlı animasyon
    // stepKm = (aracHizi km/h) * (zaman carpani) * dt(saniye) / 3600
    // Yani simTimeMul = saatin ne kadar hizli aktigi; simVehicleSpeedKmh
    // ise aracin gercek hizi (enerji modeli icin onemli).
    let raf = 0
    let lastTs = performance.now()
    const tick = (now: number) => {
      const dt = (now - lastTs) / 1000 // saniye
      lastTs = now
      const stepKm = (simVehicleSpeedKmh * simTimeMul * dt) / 3600
      setSimKm((prev) => {
        const next = prev + stepKm
        if (next >= totalKm) {
          setSimRunning(false)
          setSimArrived(true)
          return totalKm
        }
        return next
      })
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [
    navigationMode,
    simEnabled,
    simRunning,
    simVehicleSpeedKmh,
    simTimeMul,
    hasRoute,
    cumulativeDistances,
    geometry,
    // simKm intentionally NOT in deps — değişince loop yeniden kurulmamalı
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ])

  // Sim aktifken pozisyonu App'e ilet — useDynamicRerouting bunu canli konum
  // gibi kullanir. Sim kapaninca null gonder ki hook anchor'u sifirlasin.
  useEffect(() => {
    if (!onSimPositionUpdate) return
    if (simEnabled && pos) {
      onSimPositionUpdate({
        lat: pos.lat,
        lon: pos.lon,
        heading,
        // simRunning false ise arac duruyor (kullanici durakta) — hizi 0 ver
        speedKmh: simRunning ? simVehicleSpeedKmh : 0,
      })
    } else if (!simEnabled) {
      onSimPositionUpdate(null)
    }
  }, [
    simEnabled,
    simRunning,
    pos,
    heading,
    simVehicleSpeedKmh,
    onSimPositionUpdate,
  ])

  // simKm değişince pozisyonu güncelle (sim duraklasa da harita doğru)
  useEffect(() => {
    if (!simEnabled || !hasRoute) return
    const totalKm = cumulativeDistances[cumulativeDistances.length - 1] || 0
    if (totalKm <= 0) return
    const clamped = Math.max(0, Math.min(simKm, totalKm))
    // Hangi segmentteyiz?
    let idx = 0
    for (let i = 0; i < cumulativeDistances.length - 1; i++) {
      if (cumulativeDistances[i + 1] >= clamped) {
        idx = i
        break
      }
      idx = i + 1
    }
    const segStart = cumulativeDistances[idx]
    const segEnd = cumulativeDistances[Math.min(idx + 1, geometry.length - 1)]
    const t = segEnd > segStart ? (clamped - segStart) / (segEnd - segStart) : 0
    const lat =
      geometry[idx][0] +
      (geometry[Math.min(idx + 1, geometry.length - 1)][0] - geometry[idx][0]) * t
    const lon =
      geometry[idx][1] +
      (geometry[Math.min(idx + 1, geometry.length - 1)][1] - geometry[idx][1]) * t
    setPos({ lat, lon })

    // Heading: tek segment titriyor — birkaç (yaklasik 200m) ileri bak,
    // ortalama bearing = daha duzgun rotasyon.
    const targetKm = Math.min(clamped + 0.2, totalKm)
    let aheadIdx = idx
    for (let i = idx; i < cumulativeDistances.length; i++) {
      if (cumulativeDistances[i] >= targetKm) {
        aheadIdx = i
        break
      }
      aheadIdx = i
    }
    if (aheadIdx > idx) {
      setHeading(
        bearingDeg(lat, lon, geometry[aheadIdx][0], geometry[aheadIdx][1]),
      )
    }
  }, [simKm, simEnabled, hasRoute, cumulativeDistances, geometry])

  // Sim ilerlerken bir şarj durağına ulaşılınca otomatik dur ve panel aç
  useEffect(() => {
    if (!simEnabled || !simRunning) return
    if (chargingStopIdx != null) return
    if (highlightedStops.length === 0) return

    for (let i = 0; i < highlightedStops.length; i++) {
      if (completedStops.has(i)) continue
      const stop = highlightedStops[i]
      // Aracın stop noktasını geçtiyse (ya da çok yakınındaysa) tetikle
      if (simKm >= stop.distance_along_route_km - 0.3) {
        setChargingStopIdx(i)
        setSimRunning(false)
        break
      }
    }
  }, [simKm, simEnabled, simRunning, highlightedStops, completedStops, chargingStopIdx])

  const handleChargingDone = () => {
    if (chargingStopIdx == null) return
    setCompletedStops((prev) => new Set(prev).add(chargingStopIdx))
    setChargingStopIdx(null)
    setSimRunning(true)
  }

  // Sim sıfırla
  const handleSimReset = () => {
    setSimKm(0)
    setSimArrived(false)
    setSimRunning(false)
    setChargingStopIdx(null)
    setCompletedStops(new Set())
  }

  // Sim aç/kapat
  const handleSimToggle = () => {
    if (!simEnabled) {
      // Aç: GPS kapanır, sim başlangıçtan oynamaya hazır
      setSimEnabled(true)
      setSimKm(0)
      setSimArrived(false)
      setSimRunning(true)
      setChargingStopIdx(null)
      setCompletedStops(new Set())
    } else {
      // Kapat: sim durur, GPS geri açılır
      setSimEnabled(false)
      setSimRunning(false)
      setSimKm(0)
      setSimArrived(false)
      setChargingStopIdx(null)
      setCompletedStops(new Set())
    }
  }

  // Follow mode — haritayi GPS pozisyonuna kilitle.
  // Padding=0: arac ekranin tam ortasinda durur (kullanici tercihi).
  // Sim modunda rAF her 16ms tetikledigi icin easeTo cok kisa olmali ki
  // gecisler ust uste binip yarida kesilmesin.
  useEffect(() => {
    if (!navigationMode || !followMode || !pos || !mapRef.current) return
    const map = mapRef.current.getMap()
    const padding = { top: 0, bottom: 0, left: 0, right: 0 }
    if (simEnabled) {
      map.jumpTo({
        center: [pos.lon, pos.lat],
        bearing: heading,
        pitch,
        zoom: 17,
        padding,
      })
    } else {
      map.easeTo({
        center: [pos.lon, pos.lat],
        bearing: heading,
        pitch,
        zoom: 17.5,
        duration: 800,
        padding,
      })
    }
  }, [pos, heading, followMode, pitch, navigationMode, simEnabled])

  // Pitch değişince haritaya uygula
  useEffect(() => {
    if (!mapRef.current) return
    const map = mapRef.current.getMap()
    map.easeTo({
      pitch: navigationMode ? pitch : 30,
      duration: 400,
    })
  }, [pitch, navigationMode])

  // Bulunduğumuz segmenti bulup hız sınırını çıkar
  useEffect(() => {
    if (!pos || !hasRoute || !speedLimits || speedLimits.length === 0) {
      setCurrentSegmentIdx(null)
      return
    }
    let bestIdx = -1
    let bestDist = Infinity
    for (let i = 0; i < geometry.length; i++) {
      const d = haversineKm(pos.lat, pos.lon, geometry[i][0], geometry[i][1])
      if (d < bestDist) {
        bestDist = d
        bestIdx = i
      }
    }
    if (bestDist > 1.0) {
      setCurrentSegmentIdx(null)
      return
    }
    const seg = speedLimits.find(
      (s) => bestIdx >= s.start_index && bestIdx <= s.end_index,
    )
    setCurrentSegmentIdx(seg ? speedLimits.indexOf(seg) : null)
  }, [pos, geometry, speedLimits, hasRoute])

  const currentSpeedLimit =
    currentSegmentIdx != null && speedLimits
      ? speedLimits[currentSegmentIdx]?.maxspeed_kmh ?? null
      : null

  // Şarj olunan durağın detayları + curve fetch
  const chargingStop =
    chargingStopIdx != null ? highlightedStops[chargingStopIdx] : null

  const chargingCurveQ = useQuery({
    queryKey: [
      'sim-charging-curve',
      vehicleId,
      chargingStop?.power_kw,
      chargingStop?.arrival_soc_percent,
      chargingStop?.target_soc_percent,
    ],
    queryFn: () =>
      postChargingCurve({
        vehicle_id: vehicleId!,
        station_kw: chargingStop!.power_kw ?? 50,
        start_soc_pct: chargingStop!.arrival_soc_percent ?? 20,
        target_soc_pct: chargingStop!.target_soc_percent ?? 80,
      }),
    enabled:
      !!vehicleId &&
      !!chargingStop &&
      (chargingStop.power_kw ?? 0) > 0 &&
      (chargingStop.target_soc_percent ?? 0) >
        (chargingStop.arrival_soc_percent ?? 0),
    staleTime: 60_000,
  })

  // Şarj animasyonu — SOC dolmaya başlasın, kW azalsın
  const [chargeProgress, setChargeProgress] = useState(0) // 0..1
  const [animatedSoc, setAnimatedSoc] = useState(0)
  const [animatedKw, setAnimatedKw] = useState(0)
  const [animatedTimeMin, setAnimatedTimeMin] = useState(0)

  useEffect(() => {
    if (!chargingStop || !chargingCurveQ.data) return
    const points = chargingCurveQ.data.points
    if (points.length < 2) return

    // Başlangıç değerleri
    setChargeProgress(0)
    setAnimatedSoc(points[0].soc_pct)
    setAnimatedKw(points[0].power_kw)
    setAnimatedTimeMin(0)

    const totalRealMin = chargingCurveQ.data.total_minutes
    // Animasyonu demo (zaman) carpanina gore kompakte et: 1x hizda 6sn, 8x hizda ~2sn
    const animDurationMs = Math.max(
      2000,
      Math.min(8000, (totalRealMin * 60 * 1000) / Math.max(simTimeMul, 1) / 8),
    )
    const totalCurveMin = points[points.length - 1].time_min

    let raf = 0
    const startTs = performance.now()

    const tick = (now: number) => {
      const elapsed = now - startTs
      const t = Math.min(1, elapsed / animDurationMs)
      setChargeProgress(t)

      const targetTimeMin = t * totalCurveMin
      // points içinde lerp
      let idx = 0
      for (let i = 0; i < points.length - 1; i++) {
        if (points[i + 1].time_min >= targetTimeMin) {
          idx = i
          break
        }
        idx = i
      }
      const a = points[idx]
      const b = points[Math.min(idx + 1, points.length - 1)]
      const localT =
        b.time_min > a.time_min
          ? (targetTimeMin - a.time_min) / (b.time_min - a.time_min)
          : 0
      setAnimatedSoc(a.soc_pct + (b.soc_pct - a.soc_pct) * localT)
      setAnimatedKw(a.power_kw + (b.power_kw - a.power_kw) * localT)
      setAnimatedTimeMin(targetTimeMin)

      if (t < 1) {
        raf = requestAnimationFrame(tick)
      }
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [chargingStop, chargingCurveQ.data, simTimeMul])

  // Animasyon bitince otomatik devam (küçük gecikmeyle)
  useEffect(() => {
    if (chargeProgress >= 1 && chargingStop) {
      const t = setTimeout(() => handleChargingDone(), 900)
      return () => clearTimeout(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chargeProgress])

  // Anlik tuketim (kWh/km): backend energy_model.IDEAL_SPEED_KMH=90 ile uyumlu
  // hiz egrisi -> base * (v/90)^1.7. base = total_energy/total_km tercih edilir;
  // yoksa vehicle ideal_consumption_wh_km/1000; yoksa 0.18 (Avr genel deger).
  const consumptionKwhPerKm = useMemo(() => {
    const totalKm = cumulativeDistances[cumulativeDistances.length - 1] || 0
    let base: number
    if (totalEnergyKwh != null && totalEnergyKwh > 0 && totalKm > 0) {
      base = totalEnergyKwh / totalKm
    } else if (idealConsumptionWhKm != null && idealConsumptionWhKm > 0) {
      base = idealConsumptionWhKm / 1000
    } else {
      base = 0.18
    }
    const v = Math.max(5, simVehicleSpeedKmh)
    const speedFactor = Math.pow(v / 90, 1.7)
    return base * speedFactor
  }, [
    totalEnergyKwh,
    idealConsumptionWhKm,
    cumulativeDistances,
    simVehicleSpeedKmh,
  ])

  // Sim'de o anki batarya SOC'si — ENERJI-TEMELLI model.
  // initialSoc'tan baslayip her km icin consumption kadar dusuyoruz.
  // Tamamlanan duraklarda SOC anlik olarak target'a siciyor.
  const currentSoc = useMemo(() => {
    if (!simEnabled || initialSocPct == null) return null

    // Sarj ediliyorsa canli animasyon degeri
    if (chargingStopIdx != null) {
      if (animatedSoc > 0) return animatedSoc
      return (
        highlightedStops[chargingStopIdx]?.arrival_soc_percent ?? initialSocPct
      )
    }

    const usable = usableBatteryKwh ?? 60 // makul varsayilan
    if (usable <= 0) return initialSocPct

    // Mesafeye gore sirali duraklar (orijinal idx korunuyor — completedStops kontrolu)
    const sortedStops = highlightedStops
      .map((stop, idx) => ({ stop, idx }))
      .filter((x) => x.stop.target_soc_percent != null)
      .sort(
        (a, b) =>
          a.stop.distance_along_route_km - b.stop.distance_along_route_km,
      )

    // Kosumsuz iteratif hesap: 0 -> simKm boyunca consumption uygula,
    // duraklara geldikce target SOC'a sicra.
    let soc = initialSocPct
    let kmCovered = 0

    const consumePctPerKm = (consumptionKwhPerKm / usable) * 100

    for (const { stop, idx } of sortedStops) {
      const stopKm = stop.distance_along_route_km
      if (stopKm > simKm) break // henuz ulasilmadi

      // 0 (veya son tamamlanan) -> stopKm: tuket
      const leg = Math.max(0, stopKm - kmCovered)
      soc -= leg * consumePctPerKm
      kmCovered = stopKm

      if (completedStops.has(idx)) {
        // Sarj olduk — target'a sicra
        soc = stop.target_soc_percent!
      } else {
        // Durakta bekliyoruz (eşik bolgesi); arrival_soc'a clamp et,
        // boylece "1 km icinde 5% dustu sonra zipladi" gibi anomali olmasin.
        if (stop.arrival_soc_percent != null) {
          soc = Math.min(soc, stop.arrival_soc_percent)
        }
        // Durakta sayac duruyor — devam etmeden donelim
        return Math.max(0, Math.min(100, soc))
      }
    }

    // Son durak (varsa) sonrasi -> simKm: tuket
    const finalLeg = Math.max(0, simKm - kmCovered)
    soc -= finalLeg * consumePctPerKm

    return Math.max(0, Math.min(100, soc))
  }, [
    simEnabled,
    initialSocPct,
    simKm,
    highlightedStops,
    cumulativeDistances,
    completedStops,
    chargingStopIdx,
    animatedSoc,
    usableBatteryKwh,
    consumptionKwhPerKm,
  ])

  // Sim'de bir sonraki tamamlanmamış şarj durağı + ona kalan km
  const nextChargingStop = useMemo(() => {
    if (!simEnabled) return null
    const sorted = highlightedStops
      .map((stop, idx) => ({ stop, idx }))
      .sort(
        (a, b) =>
          a.stop.distance_along_route_km - b.stop.distance_along_route_km,
      )
    for (const { stop, idx } of sorted) {
      if (completedStops.has(idx)) continue
      if (stop.distance_along_route_km > simKm) {
        return {
          stop,
          idx,
          kmAway: stop.distance_along_route_km - simKm,
        }
      }
    }
    return null
  }, [simEnabled, highlightedStops, simKm, completedStops])

  // Varışa kalan ROAD mesafesi (sim modunda total - simKm,
  // GPS modunda pozisyonun rota üzerindeki projeksiyonundan kalan)
  const remainingRoadKm = useMemo(() => {
    if (!hasRoute) return null
    const totalKm = cumulativeDistances[cumulativeDistances.length - 1] || 0
    if (totalKm <= 0) return null

    if (simEnabled) {
      return Math.max(0, totalKm - simKm)
    }
    if (!pos) return null
    // En yakın geometry noktasını bul, oradaki cumulative_km'i kullan
    let bestIdx = 0
    let bestDist = Infinity
    for (let i = 0; i < geometry.length; i++) {
      const d = haversineKm(pos.lat, pos.lon, geometry[i][0], geometry[i][1])
      if (d < bestDist) {
        bestDist = d
        bestIdx = i
      }
    }
    // Rota'dan çok uzaksa (>2 km) road-distance güvenilmez, haversine'e düş
    if (bestDist > 2.0 && end) {
      return haversineKm(pos.lat, pos.lon, end.lat, end.lon)
    }
    return Math.max(0, totalKm - cumulativeDistances[bestIdx])
  }, [hasRoute, cumulativeDistances, geometry, simEnabled, simKm, pos, end])

  // 3D bina extrusion layer ekle (openfreemap liberty stilinde 'building' source layer var)
  const handleMapLoad = () => {
    const map = mapRef.current?.getMap()
    if (!map) return

    const sourceLayer = 'building'
    // Stilde böyle bir source layer var mı? Liberty style 'openmaptiles' source kullanıyor.
    if (!map.getSource('openmaptiles')) return
    if (map.getLayer('3d-buildings')) return

    try {
      map.addLayer(
        {
          id: '3d-buildings',
          source: 'openmaptiles',
          'source-layer': sourceLayer,
          type: 'fill-extrusion',
          minzoom: 14,
          paint: {
            'fill-extrusion-color': [
              'interpolate',
              ['linear'],
              ['get', 'render_height'],
              0,
              '#cbd5e1',
              50,
              '#94a3b8',
              200,
              '#64748b',
            ],
            'fill-extrusion-height': [
              'interpolate',
              ['linear'],
              ['zoom'],
              14,
              0,
              15,
              ['get', 'render_height'],
            ],
            'fill-extrusion-base': ['get', 'render_min_height'],
            'fill-extrusion-opacity': 0.85,
          },
        },
        // Yol etiketleri varsa onların altına yerleştir
        map.getLayer('place_other') ? 'place_other' : undefined,
      )
    } catch {
      // 3D bina layer'ı eklenemezse sessizce geç (style farklı olabilir)
    }
  }

  return (
    <div className="absolute inset-0">
      <Map
        ref={mapRef}
        mapLib={maplibregl as unknown as never}
        initialViewState={{
          longitude: initialView.lng,
          latitude: initialView.lat,
          zoom: initialView.zoom,
          pitch: 30,
          bearing: 0,
        }}
        mapStyle={MAP_STYLE}
        style={{ width: '100%', height: '100%' }}
        onLoad={handleMapLoad}
        onDragStart={() => navigationMode && setFollowMode(false)}
        // react-map-gl props arasinda 'preserveDrawingBuffer' tiplenmemis ama
        // alttaki MapLibre constructor'ina geciyor; canvas.toDataURL bos
        // dondurmesin diye gerekli (PDF/PNG export icin).
        {...({ preserveDrawingBuffer: true } as Record<string, unknown>)}
      >
        {!navigationMode && (
          <NavigationControl position="top-right" visualizePitch />
        )}

        {/* Sim aktif değilse: tek parça mavi rota */}
        {routeGeoJson && !splitRoute && (
          <Source id="route" type="geojson" data={routeGeoJson}>
            <Layer
              id="route-line-bg"
              type="line"
              paint={{
                'line-color': '#1e293b',
                'line-width': 9,
                'line-opacity': 0.6,
              }}
              layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            />
            <Layer
              id="route-line"
              type="line"
              paint={{
                'line-color': '#4f46e5',
                'line-width': 6,
                'line-opacity': 0.95,
              }}
              layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            />
          </Source>
        )}

        {/* Sim aktif: traveled (gri/şeffaf) + remaining (parlak mavi) */}
        {splitRoute && (
          <>
            <Source id="route-traveled" type="geojson" data={splitRoute.traveled}>
              <Layer
                id="route-traveled-line"
                type="line"
                paint={{
                  'line-color': '#94a3b8',
                  'line-width': 4,
                  'line-opacity': 0.35,
                  'line-dasharray': [2, 1],
                }}
                layout={{ 'line-cap': 'round', 'line-join': 'round' }}
              />
            </Source>
            <Source id="route-remaining" type="geojson" data={splitRoute.remaining}>
              <Layer
                id="route-remaining-bg"
                type="line"
                paint={{
                  'line-color': '#0f172a',
                  'line-width': 9,
                  'line-opacity': 0.55,
                }}
                layout={{ 'line-cap': 'round', 'line-join': 'round' }}
              />
              <Layer
                id="route-remaining-line"
                type="line"
                paint={{
                  'line-color': '#4f46e5',
                  'line-width': 6,
                  'line-opacity': 1,
                }}
                layout={{ 'line-cap': 'round', 'line-join': 'round' }}
              />
            </Source>
          </>
        )}

        {start && (
          <Marker longitude={start.lon} latitude={start.lat} anchor="bottom">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-500 text-xs font-bold text-white shadow-lg ring-2 ring-white">
              A
            </div>
          </Marker>
        )}
        {end && (
          <Marker longitude={end.lon} latitude={end.lat} anchor="bottom">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-red-500 text-xs font-bold text-white shadow-lg ring-2 ring-white">
              B
            </div>
          </Marker>
        )}

        {stations.map((s, idx) => {
          if (s.latitude == null || s.longitude == null) return null
          return (
            <Marker
              key={s.ocm_id ?? idx}
              longitude={s.longitude}
              latitude={s.latitude}
              anchor="center"
              onClick={(e) => {
                e.originalEvent.stopPropagation()
                setActiveStation(idx)
              }}
            >
              <div className="h-4 w-4 cursor-pointer rounded-full bg-emerald-500 ring-2 ring-white shadow-md" />
            </Marker>
          )
        })}

        {activeStation != null &&
          stations[activeStation]?.latitude != null &&
          stations[activeStation]?.longitude != null && (
            <Popup
              longitude={stations[activeStation].longitude!}
              latitude={stations[activeStation].latitude!}
              onClose={() => setActiveStation(null)}
              closeOnClick={false}
              anchor="top"
            >
              <div className="text-sm">
                <div className="font-semibold">
                  {stations[activeStation].name ?? 'İstasyon'}
                </div>
                {stations[activeStation].power_kw != null && (
                  <div>{stations[activeStation].power_kw} kW DC</div>
                )}
                {stations[activeStation].distance_from_route_km != null && (
                  <div className="text-xs text-slate-500">
                    Sapma:{' '}
                    {stations[activeStation].distance_from_route_km!.toFixed(2)}{' '}
                    km
                  </div>
                )}
              </div>
            </Popup>
          )}

        {/* Aktif profilin önerilen şarj durakları — numaralı, vurgulu */}
        {highlightedPositions.map((stop, idx) => (
          <Marker
            key={`stop-${idx}-${stop.lat}-${stop.lon}`}
            longitude={stop.lon}
            latitude={stop.lat}
            anchor="bottom"
          >
            <div className="flex flex-col items-center">
              <div
                className={`flex h-12 w-12 items-center justify-center rounded-full border-[3px] text-base font-bold text-white shadow-xl ${
                  stop.reserved
                    ? 'border-white bg-emerald-600'
                    : 'border-white bg-indigo-600'
                }`}
                title={`${stop.name} · ${stop.power_kw ?? '?'} kW`}
              >
                {idx + 1}
              </div>
              <div className="mt-1 max-w-[140px] truncate rounded bg-white/95 px-2 py-0.5 text-[10px] font-semibold text-slate-800 shadow">
                {stop.name}
                {stop.reserved && ' ✓'}
              </div>
            </div>
          </Marker>
        ))}

        {pos && (
          <Marker longitude={pos.lon} latitude={pos.lat} anchor="center">
            {/*
              followMode'da harita zaten heading'e döner (heading=ekran-yukari).
              Bu durumda ok yon olarak yukari bakar (rotate 0).
              Follow kapalıyken harita kuzeye sabittir; ok heading kadar dönmeli.
            */}
            <div
              style={{
                transform: `rotate(${
                  followMode && navigationMode ? 0 : heading
                }deg)`,
              }}
              className="transition-transform"
            >
              <svg width="36" height="36" viewBox="0 0 36 36">
                <circle
                  cx="18"
                  cy="18"
                  r="14"
                  fill="#3b82f6"
                  stroke="white"
                  strokeWidth="3"
                />
                <polygon points="18,6 24,20 18,16 12,20" fill="white" />
              </svg>
            </div>
          </Marker>
        )}

        {/* Canli konum marker'i — nav-mode kapaliyken her sayfada gozukur.
            Nav-mode aciksa zaten yukaridaki `pos` marker'i ayni isi yapiyor. */}
        {liveLocationVisible && liveLocation && !navigationMode && (
          <Marker
            longitude={liveLocation.lon}
            latitude={liveLocation.lat}
            anchor="center"
          >
            <div className="relative flex items-center justify-center">
              <span className="absolute h-9 w-9 animate-ping rounded-full bg-blue-500/30" />
              <span className="relative flex h-4 w-4 items-center justify-center rounded-full bg-blue-500 ring-2 ring-white shadow-md" />
            </div>
          </Marker>
        )}
      </Map>

      {/* Navigation moduna özel kontroller — haritanın üstünde absolute */}
      {navigationMode && (
        <>
          <div className="pointer-events-auto absolute bottom-6 left-1/2 z-10 flex -translate-x-1/2 items-center gap-3 rounded-full bg-slate-900/90 px-4 py-2 text-white shadow-lg">
            <label className="flex items-center gap-2 text-xs">
              <span>Eğim</span>
              <input
                type="range"
                min={0}
                max={85}
                value={pitch}
                onChange={(e) => setPitch(Number(e.target.value))}
                className="h-1 w-32 accent-emerald-500"
              />
              <span className="w-9 text-right tabular-nums">{pitch}°</span>
            </label>
            <button
              type="button"
              onClick={() => setPitch(85)}
              className="rounded-md bg-slate-700 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider hover:bg-slate-600"
              title="Maksimum eğim — araç görüntüsü"
            >
              MAX
            </button>
            <button
              onClick={() => setFollowMode((v) => !v)}
              className={`rounded-md px-3 py-1.5 text-xs ${
                followMode
                  ? 'bg-emerald-600 hover:bg-emerald-500'
                  : 'bg-slate-700 hover:bg-slate-600'
              }`}
            >
              {followMode ? 'Takip: AÇIK' : 'Takip: KAPALI'}
            </button>

            <div className="mx-1 h-5 w-px bg-slate-600" />

            {/* Simülasyon kontrolleri */}
            {!simEnabled ? (
              <button
                onClick={handleSimToggle}
                className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold hover:bg-indigo-500"
                title="GPS olmadan rotada hareketi simüle et"
              >
                ▶ Simüle Et
              </button>
            ) : (
              <>
                <button
                  onClick={() => setSimRunning((v) => !v)}
                  className={`rounded-md px-3 py-1.5 text-xs ${
                    simRunning
                      ? 'bg-amber-600 hover:bg-amber-500'
                      : 'bg-emerald-600 hover:bg-emerald-500'
                  }`}
                >
                  {simRunning ? '⏸ Duraklat' : '▶ Oynat'}
                </button>
                <label className="flex items-center gap-1 text-[10px] text-slate-300">
                  <span>Hız</span>
                  <select
                    value={simVehicleSpeedKmh}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setSimVehicleSpeedKmh(v)
                      onSimVehicleSpeedChange?.(v)
                    }}
                    className="rounded-md bg-slate-700 px-2 py-1 text-xs text-white"
                    title="Aracın gerçek hızı — enerji tüketimi bu hıza göre hesaplanır"
                  >
                    <option value={50}>50 km/h</option>
                    <option value={70}>70 km/h</option>
                    <option value={90}>90 km/h</option>
                    <option value={110}>110 km/h</option>
                    <option value={130}>130 km/h</option>
                    <option value={150}>150 km/h</option>
                  </select>
                </label>
                <label className="flex items-center gap-1 text-[10px] text-slate-300">
                  <span>Demo</span>
                  <select
                    value={simTimeMul}
                    onChange={(e) => setSimTimeMul(Number(e.target.value))}
                    className="rounded-md bg-slate-700 px-2 py-1 text-xs text-white"
                    title="Sim zaman çarpanı (yalnızca demo hızı; gerçek hızı değiştirmez)"
                  >
                    <option value={1}>1×</option>
                    <option value={4}>4×</option>
                    <option value={8}>8×</option>
                    <option value={16}>16×</option>
                    <option value={64}>64×</option>
                  </select>
                </label>
                <button
                  onClick={handleSimReset}
                  className="rounded-md bg-slate-700 px-2 py-1.5 text-xs hover:bg-slate-600"
                  title="Başa sar"
                >
                  ⟲
                </button>
                <button
                  onClick={handleSimToggle}
                  className="rounded-md bg-red-700 px-2 py-1.5 text-xs hover:bg-red-600"
                  title="Simülasyondan çık"
                >
                  ✕
                </button>
              </>
            )}
          </div>

          {gpsError && (
            <div className="pointer-events-auto absolute right-4 top-16 z-20 flex max-w-xs items-start gap-2 rounded-xl border border-amber-300 bg-white/95 px-3 py-2.5 text-xs shadow-xl backdrop-blur">
              <span className="text-base leading-none">⚠</span>
              <div className="flex-1">
                <div className="font-semibold text-amber-900">
                  Konum izni gerekli
                </div>
                <div className="mt-0.5 text-[10px] leading-snug text-slate-600">
                  3D navigasyon için tarayıcı konum erişimine izin ver veya
                  simülasyon modunu kullan.
                </div>
              </div>
              <button
                onClick={() => setGpsError(null)}
                className="rounded p-0.5 text-slate-400 hover:text-slate-700"
                aria-label="Kapat"
              >
                ✕
              </button>
            </div>
          )}

          {currentSpeedLimit != null && (
            <div className="pointer-events-none absolute bottom-24 left-6 z-10 flex flex-col items-center">
              <div
                className={`flex h-20 w-20 items-center justify-center rounded-full border-[6px] bg-white text-2xl font-bold shadow-lg ${
                  simEnabled && simVehicleSpeedKmh > currentSpeedLimit
                    ? 'animate-pulse border-red-600 text-red-600 ring-4 ring-red-500/40'
                    : 'border-red-600 text-slate-900'
                }`}
              >
                {currentSpeedLimit}
              </div>
              <div
                className={`mt-1 rounded px-2 py-0.5 text-xs font-medium ${
                  simEnabled && simVehicleSpeedKmh > currentSpeedLimit
                    ? 'bg-red-600 text-white'
                    : 'bg-slate-900/80 text-white'
                }`}
              >
                {simEnabled && simVehicleSpeedKmh > currentSpeedLimit
                  ? `${simVehicleSpeedKmh} > ${currentSpeedLimit}`
                  : 'km/h'}
              </div>
            </div>
          )}

          {/* Sim sırasında şarj durağında — animasyonlu modal */}
          {chargingStop && (
            <div
              className="pointer-events-auto absolute inset-0 z-30 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm"
              onClick={handleChargingDone}
            >
              <div
                className="w-full max-w-md overflow-hidden rounded-xl bg-white shadow-2xl"
                onClick={(e) => e.stopPropagation()}
              >
                {/* Header */}
                <div className="bg-gradient-to-r from-indigo-600 to-violet-600 px-5 py-3.5 text-white">
                  <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-indigo-100">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-300" />
                    <span>
                      Durak {chargingStopIdx! + 1} · Şarj olunuyor
                    </span>
                  </div>
                  <h3 className="text-base font-bold leading-tight">
                    {chargingStop.name}
                  </h3>
                  <div className="mt-1 flex items-center gap-3 text-[11px] text-indigo-50/90">
                    <span>⚡ {chargingStop.power_kw ?? '?'} kW</span>
                    {chargingStop.arrival_soc_percent != null &&
                      chargingStop.target_soc_percent != null && (
                        <span>
                          Hedef: %{chargingStop.arrival_soc_percent.toFixed(0)} →
                          %{chargingStop.target_soc_percent.toFixed(0)}
                        </span>
                      )}
                  </div>
                </div>

                {/* Animated body */}
                <div className="space-y-4 px-5 py-5">
                  {chargingCurveQ.isPending && (
                    <div className="py-6 text-center text-xs text-slate-500">
                      Şarj eğrisi hazırlanıyor…
                    </div>
                  )}

                  {chargingCurveQ.data &&
                    chargingCurveQ.data.points.length > 1 && (
                      <>
                        {/* Büyük animasyonlu SOC göstergesi */}
                        <div className="flex items-center gap-4">
                          {/* Battery SVG — alttan üste dolar */}
                          <div className="relative">
                            <svg
                              width="80"
                              height="120"
                              viewBox="0 0 80 120"
                              className="drop-shadow-sm"
                            >
                              {/* Battery cap */}
                              <rect
                                x="28"
                                y="0"
                                width="24"
                                height="8"
                                rx="2"
                                fill="#cbd5e1"
                              />
                              {/* Battery body outline */}
                              <rect
                                x="6"
                                y="8"
                                width="68"
                                height="108"
                                rx="6"
                                fill="white"
                                stroke="#94a3b8"
                                strokeWidth="3"
                              />
                              {/* Fill — SOC'ye göre yükselen */}
                              <rect
                                x="10"
                                y={12 + (100 - animatedSoc) / 100 * 100}
                                width="60"
                                height={(animatedSoc / 100) * 100}
                                rx="3"
                                fill={
                                  animatedSoc < 30
                                    ? '#ef4444'
                                    : animatedSoc < 70
                                    ? '#eab308'
                                    : '#22c55e'
                                }
                                style={{ transition: 'all 80ms linear' }}
                              />
                              {/* Animated bolt */}
                              <g
                                transform="translate(40 65)"
                                className="animate-pulse"
                              >
                                <path
                                  d="M-8 -16 L4 -2 L-2 -2 L6 16 L-6 0 L0 0 L-8 -16 Z"
                                  fill="white"
                                  stroke="#1e293b"
                                  strokeWidth="1.5"
                                  strokeLinejoin="round"
                                />
                              </g>
                            </svg>
                          </div>

                          {/* Live readings */}
                          <div className="flex-1 space-y-2">
                            <div>
                              <div className="text-[10px] uppercase tracking-wider text-slate-500">
                                Mevcut SOC
                              </div>
                              <div className="text-3xl font-bold tabular-nums text-slate-900">
                                %{animatedSoc.toFixed(1)}
                              </div>
                            </div>
                            <div className="flex items-center gap-3">
                              <div>
                                <div className="text-[10px] uppercase tracking-wider text-amber-700">
                                  Anlık güç
                                </div>
                                <div className="text-base font-bold tabular-nums text-amber-700">
                                  {animatedKw.toFixed(0)} kW
                                </div>
                              </div>
                              <div>
                                <div className="text-[10px] uppercase tracking-wider text-slate-500">
                                  Geçen süre
                                </div>
                                <div className="text-base font-bold tabular-nums text-slate-700">
                                  {animatedTimeMin.toFixed(1)} dk
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>

                        {/* Progress bar */}
                        <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                          <div
                            className="h-full bg-gradient-to-r from-indigo-500 to-violet-500"
                            style={{
                              width: `${chargeProgress * 100}%`,
                              transition: 'width 80ms linear',
                            }}
                          />
                        </div>

                        {/* Curve chart altta — kullanıcı görmek isterse */}
                        <ChargingCurveChart
                          points={chargingCurveQ.data.points}
                          totalMinutes={chargingCurveQ.data.total_minutes}
                          height={80}
                        />

                        <div className="grid grid-cols-3 gap-2 rounded-lg bg-slate-50 p-2 text-center text-[11px]">
                          <div>
                            <div className="text-[9px] uppercase text-slate-500">
                              Toplam Süre
                            </div>
                            <div className="font-bold text-slate-900">
                              {chargingCurveQ.data.total_minutes.toFixed(0)} dk
                            </div>
                          </div>
                          <div>
                            <div className="text-[9px] uppercase text-slate-500">
                              Eklenen
                            </div>
                            <div className="font-bold text-slate-900">
                              {(
                                ((animatedSoc -
                                  (chargingStop.arrival_soc_percent ?? 0)) /
                                  100) *
                                (chargingCurveQ.data.energy_kwh /
                                  ((chargingStop.target_soc_percent ?? 100) -
                                    (chargingStop.arrival_soc_percent ?? 0)) *
                                  100)
                              ).toFixed(1)}{' '}
                              / {chargingCurveQ.data.energy_kwh.toFixed(1)} kWh
                            </div>
                          </div>
                          <div>
                            <div className="text-[9px] uppercase text-slate-500">
                              Pik güç
                            </div>
                            <div className="font-bold text-slate-900">
                              {Math.round(
                                Math.max(
                                  ...chargingCurveQ.data.points.map(
                                    (p) => p.power_kw,
                                  ),
                                ),
                              )}{' '}
                              kW
                            </div>
                          </div>
                        </div>
                      </>
                    )}
                </div>

                {/* Footer */}
                <div className="flex items-center justify-between gap-2 border-t border-slate-200 bg-slate-50 px-5 py-3">
                  <span className="text-[10px] text-slate-500">
                    {chargeProgress >= 1
                      ? 'Şarj tamamlandı! Devam ediliyor…'
                      : 'Şarj devam ediyor…'}
                  </span>
                  <button
                    onClick={handleChargingDone}
                    className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-500"
                  >
                    {chargeProgress >= 1 ? 'Devam et' : 'Atla → Devam et'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Sim varış banner'ı */}
          {simArrived && (
            <div className="pointer-events-auto absolute top-20 left-1/2 z-20 -translate-x-1/2 rounded-xl border border-emerald-300 bg-emerald-500/95 px-6 py-4 text-center text-white shadow-2xl backdrop-blur">
              <div className="text-2xl">🏁</div>
              <div className="text-base font-bold">Varış noktasına ulaşıldı</div>
              <div className="text-xs text-emerald-100">
                Simülasyon tamamlandı. Başa sarmak için ⟲ ya da çıkmak için ✕
              </div>
            </div>
          )}

          {/* Sim aktifken birleşik üst panel: Batarya · Progress · Sıradaki Durak */}
          {simEnabled && hasRoute && (
            <div className="pointer-events-none absolute top-4 left-1/2 z-10 flex -translate-x-1/2 items-stretch overflow-hidden rounded-xl bg-slate-900/90 text-white shadow-lg backdrop-blur">
              {/* Sol: Batarya */}
              {currentSoc != null && (
                <div className="flex items-center gap-2.5 border-r border-white/10 px-4 py-2.5">
                  <svg width="26" height="38" viewBox="0 0 32 48">
                    <rect x="11" y="0" width="10" height="4" rx="1" fill="#cbd5e1" />
                    <rect
                      x="2"
                      y="4"
                      width="28"
                      height="42"
                      rx="3"
                      fill="rgba(255,255,255,0.08)"
                      stroke="white"
                      strokeWidth="2"
                    />
                    <rect
                      x="5"
                      y={7 + ((100 - currentSoc) / 100) * 36}
                      width="22"
                      height={(currentSoc / 100) * 36}
                      rx="1"
                      fill={
                        currentSoc < 20
                          ? '#ef4444'
                          : currentSoc < 50
                          ? '#eab308'
                          : '#22c55e'
                      }
                      style={{ transition: 'all 120ms linear' }}
                    />
                    {chargingStopIdx != null && (
                      <g transform="translate(16 25)">
                        <path
                          d="M-4 -8 L2 -1 L-1 -1 L3 8 L-3 1 L0 1 L-4 -8 Z"
                          fill="white"
                          className="animate-pulse"
                        />
                      </g>
                    )}
                  </svg>
                  <div className="leading-tight">
                    <div className="flex items-center gap-1">
                      <span className="text-[9px] uppercase tracking-wider text-slate-400">
                        Şarj
                      </span>
                      {chargingStopIdx != null && (
                        <span className="rounded bg-amber-500/90 px-1 py-px text-[8px] font-bold text-slate-900">
                          DOLUYOR
                        </span>
                      )}
                    </div>
                    <div
                      className={`text-lg font-bold tabular-nums ${
                        currentSoc < 20
                          ? 'text-red-400'
                          : currentSoc < 50
                          ? 'text-amber-300'
                          : 'text-emerald-300'
                      }`}
                    >
                      %{currentSoc.toFixed(0)}
                    </div>
                    {usableBatteryKwh != null && (
                      <div className="text-[9px] text-slate-400 tabular-nums">
                        {((currentSoc / 100) * usableBatteryKwh).toFixed(1)} /{' '}
                        {usableBatteryKwh.toFixed(0)} kWh
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Orta: Sim progress + hiz/tuketim ozeti */}
              <div className="flex flex-col items-center justify-center gap-1 px-5 py-2.5">
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-slate-300">SİMÜLASYON</span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${
                      currentSpeedLimit != null &&
                      simVehicleSpeedKmh > currentSpeedLimit
                        ? 'animate-pulse bg-red-600 text-white'
                        : 'bg-indigo-600 text-white'
                    }`}
                    title={
                      currentSpeedLimit != null &&
                      simVehicleSpeedKmh > currentSpeedLimit
                        ? `Hız limiti aşıldı: ${currentSpeedLimit} km/h limit, ${simVehicleSpeedKmh} km/h sim`
                        : 'Araç hızı'
                    }
                  >
                    {simVehicleSpeedKmh}
                    <span className="ml-0.5 text-[8px] opacity-80">km/h</span>
                  </span>
                  <span className="rounded bg-slate-700 px-1.5 py-0.5 text-[10px] font-bold tabular-nums">
                    {simTimeMul}×
                  </span>
                </div>
                <div className="text-sm font-bold tabular-nums">
                  {simKm.toFixed(1)} /{' '}
                  {(cumulativeDistances[cumulativeDistances.length - 1] || 0).toFixed(0)}{' '}
                  km
                </div>
                <div className="h-1 w-44 overflow-hidden rounded-full bg-slate-700">
                  <div
                    className="h-full bg-emerald-500 transition-all"
                    style={{
                      width: `${Math.min(
                        100,
                        (simKm /
                          (cumulativeDistances[cumulativeDistances.length - 1] || 1)) *
                          100,
                      )}%`,
                    }}
                  />
                </div>
                <div className="text-[9px] text-slate-400 tabular-nums">
                  Tüketim: {(consumptionKwhPerKm * 100).toFixed(1)} kWh/100km
                </div>
              </div>

              {/* Sağ: Sıradaki şarj durağı */}
              <div className="flex min-w-[140px] max-w-[180px] flex-col justify-center border-l border-white/10 px-4 py-2.5 leading-tight">
                {nextChargingStop ? (
                  <>
                    <div className="flex items-center gap-1 text-[9px] uppercase tracking-wider text-slate-400">
                      <span>⚡</span>
                      <span>Sıradaki şarj</span>
                    </div>
                    <div className="text-lg font-bold tabular-nums text-amber-300">
                      {nextChargingStop.kmAway.toFixed(1)} km
                    </div>
                    <div className="truncate text-[10px] text-slate-300">
                      {nextChargingStop.stop.name}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="text-[9px] uppercase tracking-wider text-slate-400">
                      🏁 Hedef
                    </div>
                    <div className="text-lg font-bold tabular-nums text-emerald-300">
                      {(
                        (cumulativeDistances[cumulativeDistances.length - 1] || 0) -
                        simKm
                      ).toFixed(1)}{' '}
                      km
                    </div>
                    <div className="text-[10px] text-slate-300">
                      Doğrudan varış
                    </div>
                  </>
                )}
              </div>
            </div>
          )}

          {remainingRoadKm != null && (
            <div className="absolute bottom-6 right-6 z-10 rounded-xl bg-slate-900/85 px-4 py-3 text-white shadow-lg">
              <div className="text-xs text-slate-400">Varışa kalan</div>
              <div className="text-2xl font-bold tabular-nums">
                {remainingRoadKm.toFixed(1)} km
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
