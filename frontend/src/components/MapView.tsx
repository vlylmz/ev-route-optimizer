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
  reserved?: boolean
}

interface Props {
  geometry: number[][] // [[lat, lon], ...]
  stations?: Station[]
  start?: { lat: number; lon: number }
  end?: { lat: number; lon: number }
  navigationMode?: boolean
  speedLimits?: SpeedLimitSegment[]
  highlightedStops?: HighlightedStop[]
}

const MAP_STYLE = 'https://tiles.openfreemap.org/styles/liberty'
const ANKARA_CENTER = { lng: 32.85, lat: 39.92, zoom: 6 }

function haversineKm(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const r = 6371
  const dLat = ((lat2 - lat1) * Math.PI) / 180
  const dLon = ((lon2 - lon1) * Math.PI) / 180
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2
  return 2 * r * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function bearingDeg(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const φ1 = (lat1 * Math.PI) / 180
  const φ2 = (lat2 * Math.PI) / 180
  const λ1 = (lon1 * Math.PI) / 180
  const λ2 = (lon2 * Math.PI) / 180
  const y = Math.sin(λ2 - λ1) * Math.cos(φ2)
  const x =
    Math.cos(φ1) * Math.sin(φ2) -
    Math.sin(φ1) * Math.cos(φ2) * Math.cos(λ2 - λ1)
  const brng = (Math.atan2(y, x) * 180) / Math.PI
  return (brng + 360) % 360
}

export function MapView({
  geometry,
  stations = [],
  start,
  end,
  navigationMode = false,
  speedLimits,
  highlightedStops = [],
}: Props) {
  const mapRef = useRef<MapRef | null>(null)
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
  const [simSpeedMul, setSimSpeedMul] = useState<number>(8) // 1x = gerçek hız, 8x demo
  const [simKm, setSimKm] = useState<number>(0) // şu anki kümülatif km
  const [simArrived, setSimArrived] = useState<boolean>(false)

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

  // Rota geometrisinin kümülatif mesafe profili (km)
  const cumulativeDistances = useMemo(() => {
    if (!hasRoute) return [] as number[]
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
  }, [geometry, hasRoute])

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
    let raf = 0
    let lastTs = performance.now()
    const baseSpeedKmh = 90 // sabit "yol" hızı, sonra speed limit'le çarpılabilir
    const tick = (now: number) => {
      const dt = (now - lastTs) / 1000 // saniye
      lastTs = now
      const stepKm = (baseSpeedKmh * simSpeedMul * dt) / 3600
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
    simSpeedMul,
    hasRoute,
    cumulativeDistances,
    geometry,
    // simKm intentionally NOT in deps — değişince loop yeniden kurulmamalı
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // Sim sıfırla
  const handleSimReset = () => {
    setSimKm(0)
    setSimArrived(false)
    setSimRunning(false)
  }

  // Sim aç/kapat
  const handleSimToggle = () => {
    if (!simEnabled) {
      // Aç: GPS kapanır, sim başlangıçtan oynamaya hazır
      setSimEnabled(true)
      setSimKm(0)
      setSimArrived(false)
      setSimRunning(true)
    } else {
      // Kapat: sim durur, GPS geri açılır
      setSimEnabled(false)
      setSimRunning(false)
      setSimKm(0)
      setSimArrived(false)
    }
  }

  // Follow mode — haritayı GPS pozisyonuna kilitle
  // Padding ile aracı ekranın alt 1/3'ünde tutarız (gerçek nav görünümü).
  // Sim modunda rAF her 16ms tetikledigi icin easeTo cok kisa olmali ki
  // gecisler ust uste binip yarida kesilmesin.
  useEffect(() => {
    if (!navigationMode || !followMode || !pos || !mapRef.current) return
    const map = mapRef.current.getMap()
    const canvas = map.getCanvas()
    const h = canvas.clientHeight || 700
    const padding = { top: 0, bottom: Math.round(h * 0.55), left: 0, right: 0 }
    if (simEnabled) {
      // Tight follow — aniden yapis, yumusak gecis surekli kesilmesin.
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
      >
        <NavigationControl position="top-right" visualizePitch />

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
                <select
                  value={simSpeedMul}
                  onChange={(e) => setSimSpeedMul(Number(e.target.value))}
                  className="rounded-md bg-slate-700 px-2 py-1 text-xs text-white"
                  title="Hız çarpanı (gerçek-saat × N)"
                >
                  <option value={1}>1×</option>
                  <option value={4}>4×</option>
                  <option value={8}>8×</option>
                  <option value={16}>16×</option>
                  <option value={64}>64×</option>
                </select>
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
            <div className="pointer-events-auto absolute top-4 right-4 z-20 flex max-w-xs items-start gap-2 rounded-xl border border-amber-300 bg-white/95 px-3 py-2.5 text-xs shadow-xl backdrop-blur">
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
              <div className="flex h-20 w-20 items-center justify-center rounded-full border-[6px] border-red-600 bg-white text-2xl font-bold text-slate-900 shadow-lg">
                {currentSpeedLimit}
              </div>
              <div className="mt-1 rounded bg-slate-900/80 px-2 py-0.5 text-xs font-medium text-white">
                km/h
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

          {/* Sim aktifken progress göstergesi */}
          {simEnabled && hasRoute && (
            <div className="pointer-events-none absolute top-4 left-1/2 z-10 flex -translate-x-1/2 flex-col items-center gap-1 rounded-lg bg-slate-900/85 px-4 py-2 text-white shadow-lg backdrop-blur">
              <div className="flex items-center gap-2 text-xs">
                <span className="text-slate-300">SİMÜLASYON</span>
                <span className="rounded bg-indigo-600 px-1.5 py-0.5 text-[10px] font-bold">
                  {simSpeedMul}×
                </span>
              </div>
              <div className="text-sm font-bold tabular-nums">
                {simKm.toFixed(1)} /{' '}
                {(cumulativeDistances[cumulativeDistances.length - 1] || 0).toFixed(0)}{' '}
                km
              </div>
              <div className="h-1 w-48 overflow-hidden rounded-full bg-slate-700">
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
            </div>
          )}

          {pos && end && (
            <div className="absolute bottom-6 right-6 z-10 rounded-xl bg-slate-900/85 px-4 py-3 text-white shadow-lg">
              <div className="text-xs text-slate-400">Varışa kalan</div>
              <div className="text-2xl font-bold tabular-nums">
                {haversineKm(pos.lat, pos.lon, end.lat, end.lon).toFixed(1)} km
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
