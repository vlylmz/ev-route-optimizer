import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MapRef } from 'react-map-gl/maplibre'
import {
  BarChart3,
  ChevronDown,
  Compass,
  FileDown,
  Gauge,
  History,
  Image as ImageIcon,
  Leaf,
  MapPin,
  Mountain,
  Route,
  Scale,
  Sparkles,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { RouteForm } from './components/RouteForm'
import { MapView } from './components/MapView'
import { ReportPanel } from './components/ReportPanel'
import { ElevationChart } from './components/ElevationChart'
import { RouteHistoryPanel } from './components/RouteHistoryPanel'
import {
  ReservationDialog,
  type Reservation,
} from './components/ReservationDialog'
import { useVehicles } from './hooks/useVehicles'
import { useOptimize } from './hooks/useOptimize'
import { useRoute } from './hooks/useRoute'
import { useSpeedLimits } from './hooks/useSpeedLimits'
import { useRouteHistory } from './hooks/useRouteHistory'
import { useLiveLocation, type LivePosition } from './hooks/useLiveLocation'
import { useDynamicRerouting } from './hooks/useDynamicRerouting'
import { useRouteExport } from './hooks/useRouteExport'
import { useReverseGeocode } from './hooks/useReverseGeocode'
import type {
  GeocodeResultItem,
  OptimizeRequest,
  RecommendedStop,
} from './services/schemas'

function reservationKey(strategyKey: string, idx: number): string {
  return `${strategyKey}::${idx}`
}

interface StrategyAccent {
  icon: LucideIcon
  iconBg: string
  iconColor: string
  bar: string
  activeBg: string
  activeBorder: string
  ring: string
  badgeBg: string
  badgeText: string
}

const STRATEGY_ACCENT: Record<string, StrategyAccent> = {
  fast: {
    icon: Zap,
    iconBg: 'bg-rose-500/20',
    iconColor: 'text-rose-300',
    bar: 'bg-rose-500',
    activeBg: 'bg-rose-500/15',
    activeBorder: 'border-rose-400/60',
    ring: 'ring-rose-400/30',
    badgeBg: 'bg-rose-500/90',
    badgeText: 'text-white',
  },
  efficient: {
    icon: Leaf,
    iconBg: 'bg-emerald-500/20',
    iconColor: 'text-emerald-300',
    bar: 'bg-emerald-500',
    activeBg: 'bg-emerald-500/15',
    activeBorder: 'border-emerald-400/60',
    ring: 'ring-emerald-400/30',
    badgeBg: 'bg-emerald-500/90',
    badgeText: 'text-white',
  },
  balanced: {
    icon: Scale,
    iconBg: 'bg-indigo-500/20',
    iconColor: 'text-indigo-300',
    bar: 'bg-indigo-500',
    activeBg: 'bg-indigo-500/15',
    activeBorder: 'border-indigo-400/60',
    ring: 'ring-indigo-400/30',
    badgeBg: 'bg-indigo-500/90',
    badgeText: 'text-white',
  },
}

function App() {
  const vehiclesQ = useVehicles()
  const optimizeM = useOptimize()
  const routeM = useRoute()
  const speedLimitsM = useSpeedLimits()

  const [submitted, setSubmitted] = useState<OptimizeRequest | null>(null)
  const [submittedNames, setSubmittedNames] = useState<{
    start: GeocodeResultItem
    end: GeocodeResultItem
  } | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [navMode, setNavMode] = useState(false)
  const [liveLocationOn, setLiveLocationOn] = useState(false)
  const [dynamicReroutingOn, setDynamicReroutingOn] = useState(false)
  const { pos: livePos, error: liveErr } = useLiveLocation({
    enabled: liveLocationOn,
  })
  // MapView simulation pozisyonu — sim aktifken App'e gelir, live'in yerine
  // useDynamicRerouting'a beslenir.
  const [simPos, setSimPos] = useState<LivePosition | null>(null)
  const handleSimPositionUpdate = useCallback(
    (
      next: {
        lat: number
        lon: number
        heading: number
        speedKmh: number
      } | null,
    ) => {
      if (!next) {
        setSimPos(null)
        return
      }
      setSimPos({
        lat: next.lat,
        lon: next.lon,
        heading: next.heading,
        speedKmh: next.speedKmh,
        accuracyM: 0,
        timestamp: Date.now(),
      })
    },
    [],
  )
  // useDynamicRerouting icin: sim aktifse onun pozisyonu, degilse gercek GPS.
  const effectiveLivePos: LivePosition | null = simPos ?? livePos
  // Suanki konum etiketi: sim aktifse sim pos, yoksa GPS pos.
  const reverseGeocodeQ = useReverseGeocode({
    enabled: effectiveLivePos != null,
    lat: effectiveLivePos?.lat,
    lon: effectiveLivePos?.lon,
    minMoveKm: 0.5,
    minIntervalMs: 5000,
  })
  const mapRef = useRef<MapRef | null>(null)
  const { exportPng, exportPdf } = useRouteExport()

  // Sim hızı degisince debounced reroute: kullanici 130 -> 90'a indirirken
  // her ara degeri ayri istek olmasin. 2sn bekle, son halini gonder.
  const speedRerouteTimerRef = useRef<number | null>(null)
  const handleSimVehicleSpeedChange = useCallback(
    (kmh: number) => {
      if (speedRerouteTimerRef.current != null) {
        window.clearTimeout(speedRerouteTimerRef.current)
      }
      speedRerouteTimerRef.current = window.setTimeout(() => {
        if (!submitted || !simPos) return
        // Mevcut konumdan + son sim SOC'siyle reroute. simSpeed bilgisi
        // backend'e gitmez (planner kendi modelini kullanir) ama yine de
        // mevcut konumdan yeni alternatifler uretir.
        const newReq = {
          ...submitted,
          start: { lat: simPos.lat, lon: simPos.lon },
        }
        setSubmitted(newReq)
        optimizeM.mutate(newReq)
        routeM.mutate({ start: newReq.start, end: newReq.end })
        // eslint-disable-next-line no-console
        console.info(
          `[sim] hiz degisti (${kmh} km/h) -> reroute tetiklendi`,
        )
      }, 2000)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [submitted, simPos],
  )
  useEffect(() => {
    return () => {
      if (speedRerouteTimerRef.current != null) {
        window.clearTimeout(speedRerouteTimerRef.current)
        speedRerouteTimerRef.current = null
      }
    }
  }, [])
  const [activeProfileKey, setActiveProfileKey] = useState<string | null>(null)
  const [pendingPreset, setPendingPreset] = useState<{
    start: GeocodeResultItem
    end: GeocodeResultItem
    vehicleId: string
    initialSocPct: number
    targetArrivalSocPct?: number | null
  } | null>(null)
  const history = useRouteHistory()

  // Rezervasyon state'i: key = "<strategy>::<stopIdx>"
  const [reservations, setReservations] = useState<Record<string, Reservation>>(
    {},
  )
  const [activeReservation, setActiveReservation] = useState<{
    key: string
    stop: RecommendedStop
  } | null>(null)

  const handleSubmit = (
    req: OptimizeRequest,
    extra: {
      start: GeocodeResultItem
      end: GeocodeResultItem
      preferredStrategy: 'fast' | 'efficient' | 'balanced'
    },
  ) => {
    setSubmitted(req)
    setSubmittedNames({ start: extra.start, end: extra.end })
    setReservations({}) // yeni rota → eski rezervasyonları temizle
    // Kullanıcının form'da seçtiği tercihi aktif profil olarak ayarla
    setActiveProfileKey(extra.preferredStrategy)
    optimizeM.mutate(req)
    routeM.mutate({ start: req.start, end: req.end })
  }

  // Optimize sonucu geldikten sonra rotayı geçmişe ekle
  useEffect(() => {
    const data = optimizeM.data
    if (!data || !submittedNames || !submitted) return
    const cheapest = data.profiles
      .filter((p) => p.feasible && p.total_cost_try > 0)
      .sort((a, b) => a.total_cost_try - b.total_cost_try)[0]
    history.addEntry({
      vehicleId: submitted.vehicle_id,
      vehicleName: data.vehicle_name,
      start: submittedNames.start,
      end: submittedNames.end,
      initialSocPct: submitted.initial_soc_pct,
      targetArrivalSocPct: submitted.target_arrival_soc_pct,
      totalDistanceKm: data.total_distance_km,
      totalCostTry: cheapest?.total_cost_try ?? 0,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optimizeM.data])

  const handleSelectHistory = (entry: typeof history.entries[number]) => {
    setPendingPreset({
      start: entry.start,
      end: entry.end,
      vehicleId: entry.vehicleId,
      initialSocPct: entry.initialSocPct,
      targetArrivalSocPct: entry.targetArrivalSocPct,
    })
  }

  const geometry = routeM.data?.geometry ?? []
  const stations = useMemo(
    () => (routeM.data?.stations as Array<Record<string, unknown>> | undefined) ?? [],
    [routeM.data],
  )

  // Rota geldiğinde hız limitlerini arka planda çek
  useEffect(() => {
    if (geometry.length >= 2) {
      speedLimitsM.mutate({ geometry, sample_every_n_points: 20 })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeM.data])

  // Optimize sonucu gelince, aktif profil yoksa önerilen profile'ı seç
  useEffect(() => {
    const data = optimizeM.data
    if (!data) return
    if (!activeProfileKey || !data.profiles.find((p) => p.key === activeProfileKey)) {
      setActiveProfileKey(
        data.recommended_profile ?? data.profiles[0]?.key ?? null,
      )
    }
  }, [optimizeM.data, activeProfileKey])

  // Yükseklik profili (route response'tan)
  const elevationProfile = useMemo(() => {
    const raw = (routeM.data?.elevation_profile ?? []) as Array<{
      cumulative_distance_km?: number
      elevation_m?: number
    }>
    return raw
      .filter(
        (p) =>
          typeof p.cumulative_distance_km === 'number' &&
          typeof p.elevation_m === 'number',
      )
      .map((p) => ({
        cumulative_distance_km: p.cumulative_distance_km!,
        elevation_m: p.elevation_m!,
      }))
  }, [routeM.data])

  // Aktif profilin durakları (haritada vurgulanacak)
  const activeProfileStops = useMemo(() => {
    if (!optimizeM.data || !activeProfileKey) return []
    const profile = optimizeM.data.profiles.find(
      (p) => p.key === activeProfileKey,
    )
    if (!profile) return []
    return profile.recommended_stops.map((s, idx) => {
      const key = `${profile.key}::${idx}`
      return {
        name: s.name,
        distance_along_route_km: s.distance_along_route_km,
        power_kw: s.power_kw,
        charge_minutes: s.charge_minutes,
        arrival_soc_percent: s.arrival_soc_percent,
        target_soc_percent: s.target_soc_percent,
        reserved: !!reservations[key],
      }
    })
  }, [optimizeM.data, activeProfileKey, reservations])

  // Sim batarya göstergesi için: aktif araç + aktif profilin varış SOC'si
  const activeVehicle = useMemo(
    () => vehiclesQ.data?.find((v) => v.id === submitted?.vehicle_id) ?? null,
    [vehiclesQ.data, submitted?.vehicle_id],
  )

  const activeProfileFinalSoc = useMemo(() => {
    if (!optimizeM.data || !activeProfileKey) return null
    const profile = optimizeM.data.profiles.find(
      (p) => p.key === activeProfileKey,
    )
    return profile?.final_soc_pct ?? optimizeM.data.final_soc_pct ?? null
  }, [optimizeM.data, activeProfileKey])

  // Dinamik yeniden rotalama — her 30 km'de bir mevcut rotayi arka planda
  // yeniden hesaplar. Canli konum VEYA simulasyon (sim varsa sim oncelikli)
  // aktifken calisir.
  useDynamicRerouting({
    enabled: dynamicReroutingOn && (liveLocationOn || simPos != null),
    livePos: effectiveLivePos,
    baseRequest: submitted,
    currentSocPct: activeProfileFinalSoc,
    triggerEveryKm: 30,
    onReroute: (newReq) => {
      setSubmitted(newReq)
      optimizeM.mutate(newReq)
      routeM.mutate({ start: newReq.start, end: newReq.end })
    },
  })

  const handleStartNav = () => {
    if (geometry.length < 2) return
    setNavMode(true)
    setSidebarOpen(false)
  }

  const handleStopNav = () => {
    setNavMode(false)
    setSidebarOpen(true)
  }

  const handleReserve = (
    strategyKey: string,
    stopIdx: number,
    stop: RecommendedStop,
  ) => {
    setActiveReservation({ key: reservationKey(strategyKey, stopIdx), stop })
  }

  const handleConfirmReservation = (r: Reservation) => {
    if (!activeReservation) return
    setReservations((prev) => ({ ...prev, [activeReservation.key]: r }))
    setActiveReservation(null)
  }

  const handleCancelReservation = () => {
    if (!activeReservation) return
    setReservations((prev) => {
      const next = { ...prev }
      delete next[activeReservation.key]
      return next
    })
    setActiveReservation(null)
  }

  const reservationCount = Object.keys(reservations).length

  return (
    <div className="fixed inset-0 overflow-hidden bg-slate-900">
      {/* Tam ekran harita */}
      <MapView
        geometry={geometry}
        cumulativeDistancesKm={routeM.data?.cumulative_distances ?? []}
        stations={stations as Parameters<typeof MapView>[0]['stations']}
        start={submitted?.start}
        end={submitted?.end}
        navigationMode={navMode}
        speedLimits={speedLimitsM.data?.segments ?? []}
        highlightedStops={activeProfileStops}
        vehicleId={submitted?.vehicle_id}
        initialSocPct={optimizeM.data?.initial_soc_pct}
        usableBatteryKwh={activeVehicle?.usable_battery_kwh}
        idealConsumptionWhKm={activeVehicle?.ideal_consumption_wh_km}
        totalEnergyKwh={optimizeM.data?.total_energy_kwh}
        liveLocation={livePos}
        liveLocationVisible={liveLocationOn}
        onSimPositionUpdate={handleSimPositionUpdate}
        onSimVehicleSpeedChange={handleSimVehicleSpeedChange}
        mapRef={mapRef}
      />

      {/* Sidebar Aç butonu */}
      {!sidebarOpen && (
        <button
          onClick={() => setSidebarOpen(true)}
          className="absolute left-4 top-4 z-20 flex items-center gap-2 rounded-xl border border-white/40 bg-white/85 px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-xl backdrop-blur hover:bg-white"
        >
          <span className="text-lg leading-none">☰</span>
          <span>Menü</span>
          {reservationCount > 0 && (
            <span className="rounded-full bg-emerald-500 px-2 py-0.5 text-[10px] font-bold text-white">
              {reservationCount}
            </span>
          )}
        </button>
      )}

      {/* Navigasyondan çık butonu */}
      {navMode && (
        <button
          onClick={handleStopNav}
          className="absolute right-4 top-4 z-20 rounded-xl border border-red-400/30 bg-red-600/95 px-4 py-2.5 text-sm font-semibold text-white shadow-xl backdrop-blur hover:bg-red-500"
        >
          ✕ Navigasyondan Çık
        </button>
      )}

      {/* Şu anki konum etiketi - sim/canli konum aktifken */}
      {navMode && effectiveLivePos && reverseGeocodeQ.data && (
        <div className="pointer-events-none absolute left-1/2 top-32 z-10 max-w-md -translate-x-1/2 rounded-2xl border border-white/10 bg-gradient-to-br from-slate-900/95 to-slate-800/95 px-4 py-2.5 shadow-2xl ring-1 ring-black/5 backdrop-blur-xl">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-blue-600 shadow-md ring-2 ring-blue-400/30">
              <MapPin size={14} className="text-white" />
            </div>
            <div className="min-w-0 leading-tight">
              <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-400">
                Şu an
              </div>
              <div className="line-clamp-2 max-w-[320px] text-xs font-semibold text-white">
                {reverseGeocodeQ.data.display_name}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Alternatif rotalar paneli - sim aktifken, sag tarafta */}
      {navMode &&
        simPos != null &&
        optimizeM.data &&
        optimizeM.data.profiles.length > 1 && (
          <aside className="pointer-events-auto absolute right-4 top-44 z-10 flex w-64 flex-col gap-2 rounded-2xl border border-white/10 bg-gradient-to-br from-slate-900/95 to-slate-800/95 p-3 text-white shadow-2xl ring-1 ring-black/5 backdrop-blur-xl">
            <div className="flex items-center justify-between px-0.5">
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-300">
                <Route size={12} className="text-indigo-400" />
                <span>Alternatifler</span>
              </div>
              {optimizeM.isPending && (
                <span className="flex items-center gap-1 text-[9px] font-semibold uppercase tracking-wider text-amber-300">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
                  Hesap…
                </span>
              )}
            </div>
            {optimizeM.data.profiles
              .filter((p) => p.feasible)
              .map((p) => {
                const isActive = p.key === activeProfileKey
                const accent = STRATEGY_ACCENT[p.key] ?? STRATEGY_ACCENT.balanced
                const Icon = accent.icon
                return (
                  <button
                    key={p.key}
                    onClick={() => setActiveProfileKey(p.key)}
                    className={`group relative overflow-hidden rounded-xl border px-3 py-2.5 text-left transition active:scale-[0.98] ${
                      isActive
                        ? `${accent.activeBorder} ${accent.activeBg} ring-1 ${accent.ring} shadow-lg`
                        : 'border-white/5 bg-white/5 hover:border-white/10 hover:bg-white/10'
                    }`}
                  >
                    {/* Sol kenar accent */}
                    <span
                      className={`absolute inset-y-0 left-0 w-1 ${
                        isActive ? accent.bar : 'bg-transparent'
                      }`}
                    />
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <div
                          className={`flex h-6 w-6 items-center justify-center rounded-md ${accent.iconBg}`}
                        >
                          <Icon size={12} className={accent.iconColor} />
                        </div>
                        <span
                          className={`text-xs font-bold ${
                            isActive ? 'text-white' : 'text-slate-200'
                          }`}
                        >
                          {p.label}
                        </span>
                      </div>
                      {isActive && (
                        <span className={`rounded-md px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wider ${accent.badgeBg} ${accent.badgeText}`}>
                          ✓ Aktif
                        </span>
                      )}
                    </div>
                    <div className="mt-1.5 flex items-center gap-2.5 text-[10px] tabular-nums">
                      <span className="font-semibold text-white">
                        {(p.total_trip_minutes ?? 0).toFixed(0)}
                        <span className="ml-0.5 font-medium text-slate-400">
                          dk
                        </span>
                      </span>
                      <span className="text-slate-600">·</span>
                      <span className="font-semibold text-white">
                        {p.stop_count ?? 0}
                        <span className="ml-0.5 font-medium text-slate-400">
                          durak
                        </span>
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2.5 text-[10px] tabular-nums text-slate-400">
                      <span>
                        {(p.total_energy_kwh ?? 0).toFixed(1)}
                        <span className="ml-0.5">kWh</span>
                      </span>
                      <span className="text-slate-600">·</span>
                      <span className="font-semibold text-emerald-300">
                        ₺{p.total_cost_try.toFixed(0)}
                      </span>
                    </div>
                  </button>
                )
              })}
          </aside>
        )}

      {/* Sidebar */}
      {sidebarOpen && (
        <aside className="absolute left-0 top-0 z-20 flex h-full w-full flex-col overflow-y-auto border-r border-white/40 bg-white/80 shadow-2xl backdrop-blur-xl sm:w-[440px]">
          {/* Compact header — tek satır */}
          <div className="relative flex items-center justify-between border-b border-slate-200 bg-white/95 px-5 py-3 backdrop-blur">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-600 to-violet-600 text-white shadow-sm">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                </svg>
              </div>
              <div className="leading-tight">
                <h1 className="text-sm font-bold text-slate-900">
                  EV Route Optimizer
                </h1>
                <p className="text-[10px] text-slate-500">
                  Rota · Enerji · Şarj
                </p>
              </div>
            </div>
            <button
              onClick={() => setSidebarOpen(false)}
              className="rounded-xl p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
              aria-label="Kapat"
            >
              ✕
            </button>
          </div>

          {/* İçerik */}
          <div className="flex-1 space-y-5 px-5 py-5">
            <Section title="Rota & Araç" icon={MapPin}>
              <RouteForm
                vehicles={vehiclesQ.data ?? []}
                vehiclesLoading={vehiclesQ.isLoading}
                vehiclesError={vehiclesQ.isError}
                onSubmit={handleSubmit}
                isSubmitting={optimizeM.isPending || routeM.isPending}
                presetStart={pendingPreset?.start}
                presetEnd={pendingPreset?.end}
                presetVehicleId={pendingPreset?.vehicleId}
                presetInitialSocPct={pendingPreset?.initialSocPct}
                presetTargetArrivalSocPct={pendingPreset?.targetArrivalSocPct}
              />
            </Section>

            {history.entries.length > 0 && (
              <Section
                title="Son Rotalar"
                icon={History}
                collapsible
                defaultOpen={false}
                badge={
                  <span className="ml-1 rounded-full bg-slate-200 px-1.5 py-0 text-[9px] font-bold text-slate-600">
                    {history.entries.length}
                  </span>
                }
              >
                <RouteHistoryPanel
                  entries={history.entries}
                  onSelect={handleSelectHistory}
                  onRemove={history.removeEntry}
                  onClearAll={history.clearAll}
                />
              </Section>
            )}

            {optimizeM.isPending && (
              <div className="flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50/80 px-3 py-2.5 text-xs text-indigo-700 backdrop-blur">
                <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
                Rota optimize ediliyor… (OSRM + eğim + hava + istasyon)
              </div>
            )}

            {optimizeM.isError && (
              <div className="rounded-lg border border-red-200 bg-red-50/80 p-3 text-xs text-red-700 backdrop-blur">
                <div className="font-semibold">Hata</div>
                <div>{optimizeM.error.message}</div>
              </div>
            )}

            {geometry.length >= 2 && (
              <button
                onClick={handleStartNav}
                className="group relative w-full overflow-hidden rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 py-3.5 text-sm font-bold text-white shadow-lg transition hover:shadow-xl active:scale-[0.99]"
              >
                <span className="absolute inset-0 bg-gradient-to-r from-indigo-400/0 via-white/20 to-indigo-400/0 opacity-0 transition group-hover:opacity-100" />
                <span className="relative flex items-center justify-center gap-2">
                  <Compass size={16} />
                  <span>Yola Çık · 3D Navigasyon</span>
                </span>
              </button>
            )}

            {optimizeM.data && activeProfileKey && geometry.length >= 2 && (
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => {
                    const profile = optimizeM.data!.profiles.find(
                      (p) => p.key === activeProfileKey,
                    )
                    if (!profile) return
                    exportPng({
                      mapRef,
                      stops: profile.recommended_stops,
                      meta: {
                        vehicleName: optimizeM.data!.vehicle_name,
                        startLabel:
                          submittedNames?.start.display_name ?? 'Başlangıç',
                        endLabel: submittedNames?.end.display_name ?? 'Bitiş',
                        distanceKm: optimizeM.data!.total_distance_km,
                        durationMin: profile.total_trip_minutes ?? 0,
                        initialSocPct: optimizeM.data!.initial_soc_pct,
                        finalSocPct: profile.final_soc_pct,
                        strategyLabel: profile.label,
                      },
                    })
                  }}
                  className="flex items-center justify-center gap-1.5 rounded-xl border border-slate-300 bg-white/70 px-3 py-2.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-white hover:shadow"
                >
                  <ImageIcon size={14} />
                  PNG indir
                </button>
                <button
                  onClick={() => {
                    const profile = optimizeM.data!.profiles.find(
                      (p) => p.key === activeProfileKey,
                    )
                    if (!profile) return
                    exportPdf({
                      mapRef,
                      stops: profile.recommended_stops,
                      meta: {
                        vehicleName: optimizeM.data!.vehicle_name,
                        startLabel:
                          submittedNames?.start.display_name ?? 'Başlangıç',
                        endLabel: submittedNames?.end.display_name ?? 'Bitiş',
                        distanceKm: optimizeM.data!.total_distance_km,
                        durationMin: profile.total_trip_minutes ?? 0,
                        initialSocPct: optimizeM.data!.initial_soc_pct,
                        finalSocPct: profile.final_soc_pct,
                        strategyLabel: profile.label,
                      },
                    })
                  }}
                  className="flex items-center justify-center gap-1.5 rounded-xl border border-slate-300 bg-white/70 px-3 py-2.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-white hover:shadow"
                >
                  <FileDown size={14} />
                  PDF indir
                </button>
              </div>
            )}

            {geometry.length >= 2 && (
              <div className="flex items-center justify-between rounded-xl border border-slate-200/70 bg-white/60 px-3 py-2 text-xs text-slate-600 backdrop-blur">
                <span className="flex items-center gap-2 text-slate-500">
                  <Gauge size={13} />
                  <span>Hız limitleri</span>
                </span>
                {speedLimitsM.isPending && (
                  <span className="text-amber-600">yükleniyor…</span>
                )}
                {speedLimitsM.data && (
                  <span className="font-semibold text-emerald-600">
                    {speedLimitsM.data.segments.length} segment ·{' '}
                    {speedLimitsM.data.source}
                  </span>
                )}
              </div>
            )}

            <div className="rounded-xl border border-slate-200/70 bg-white/60 px-3 py-2 text-xs text-slate-600 backdrop-blur">
              <label className="flex cursor-pointer items-center justify-between gap-2">
                <span className="flex items-center gap-2">
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${
                      liveLocationOn && livePos
                        ? 'animate-pulse bg-blue-500'
                        : 'bg-slate-300'
                    }`}
                  />
                  <span className="font-medium">Canlı konum</span>
                </span>
                <input
                  type="checkbox"
                  checked={liveLocationOn}
                  onChange={(e) => setLiveLocationOn(e.target.checked)}
                  className="h-3.5 w-3.5 accent-blue-600"
                />
              </label>
              {liveLocationOn && livePos && (
                <div className="mt-1.5 flex items-center justify-between text-[10px] text-slate-500">
                  <span className="tabular-nums">
                    {livePos.lat.toFixed(5)}, {livePos.lon.toFixed(5)}
                  </span>
                  <span className="tabular-nums">
                    ±{livePos.accuracyM.toFixed(0)} m
                  </span>
                </div>
              )}
              {liveLocationOn && liveErr && (
                <div className="mt-1.5 text-[10px] text-red-600">
                  {liveErr}
                </div>
              )}
            </div>

            <div
              className={`rounded-xl border px-3 py-2 text-xs backdrop-blur ${
                liveLocationOn
                  ? 'border-slate-200/70 bg-white/60 text-slate-600'
                  : 'border-slate-200/50 bg-white/40 text-slate-400'
              }`}
            >
              <label
                className={`flex items-center justify-between gap-2 ${
                  liveLocationOn ? 'cursor-pointer' : 'cursor-not-allowed'
                }`}
              >
                <span className="flex items-center gap-2">
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${
                      dynamicReroutingOn && liveLocationOn
                        ? 'animate-pulse bg-violet-500'
                        : 'bg-slate-300'
                    }`}
                  />
                  <span className="font-medium">Dinamik rotalama</span>
                  <span className="text-[10px] text-slate-400">
                    (her 30 km)
                  </span>
                </span>
                <input
                  type="checkbox"
                  checked={dynamicReroutingOn}
                  disabled={!liveLocationOn}
                  onChange={(e) => setDynamicReroutingOn(e.target.checked)}
                  className="h-3.5 w-3.5 accent-violet-600 disabled:opacity-40"
                />
              </label>
              {!liveLocationOn && (
                <div className="mt-1 text-[10px] text-slate-400">
                  Canlı konum gerekli
                </div>
              )}
            </div>

            {reservationCount > 0 && (
              <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50/80 px-3 py-2 text-xs text-emerald-800 backdrop-blur">
                <span className="flex items-center gap-2">
                  <span>✓</span>
                  <span>Aktif rezervasyon</span>
                </span>
                <span className="font-bold text-emerald-700">
                  {reservationCount}
                </span>
              </div>
            )}

            {optimizeM.data && elevationProfile.length >= 2 && (
              <Section
                title="Yükseklik Profili"
                icon={Mountain}
                collapsible
                defaultOpen={false}
              >
                <ElevationChart
                  profile={elevationProfile}
                  highlightedStops={activeProfileStops.map((s) => ({
                    distance_along_route_km: s.distance_along_route_km,
                    name: s.name,
                  }))}
                />
              </Section>
            )}

            {optimizeM.data && (
              <Section title="Sonuç" icon={BarChart3}>
                <ReportPanel
                  result={optimizeM.data}
                  reservations={reservations}
                  onReserve={handleReserve}
                  activeProfileKey={activeProfileKey}
                  onSelectProfile={(key) => setActiveProfileKey(key)}
                />
              </Section>
            )}

            {!optimizeM.data && !optimizeM.isPending && (
              <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-300 bg-slate-50/60 p-6 text-center text-xs text-slate-500 backdrop-blur">
                <Sparkles size={28} className="text-indigo-300" />
                <div className="font-semibold text-slate-700">Henüz plan yok</div>
                <div>
                  Rota bilgilerini doldurup
                  <br />
                  "Rotayı Optimize Et" butonuna bas.
                </div>
              </div>
            )}
          </div>

          <a
            href="http://127.0.0.1:8000/docs"
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-center gap-2 border-t border-slate-200/70 bg-white/50 px-5 py-3 text-xs font-medium text-indigo-600 transition hover:bg-white/80"
          >
            <span>API dokümanı</span>
            <span aria-hidden>↗</span>
          </a>
        </aside>
      )}

      {/* Rezervasyon dialog */}
      {activeReservation && (
        <ReservationDialog
          stop={activeReservation.stop}
          existingReservation={reservations[activeReservation.key] ?? null}
          vehicleId={submitted?.vehicle_id}
          onClose={() => setActiveReservation(null)}
          onConfirm={handleConfirmReservation}
          onCancel={handleCancelReservation}
        />
      )}

    </div>
  )
}

function Section({
  title,
  icon: Icon,
  children,
  collapsible = false,
  defaultOpen = true,
  badge,
}: {
  title: string
  icon: React.ComponentType<{ size?: number; className?: string }>
  children: React.ReactNode
  collapsible?: boolean
  defaultOpen?: boolean
  badge?: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const isOpen = collapsible ? open : true

  if (collapsible) {
    return (
      <section className="rounded-xl border border-slate-200 bg-white/40 backdrop-blur">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center justify-between px-3 py-2 text-left"
        >
          <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-600">
            <Icon size={12} className="text-slate-400" />
            <span>{title}</span>
            {badge}
          </div>
          <ChevronDown
            size={14}
            className={
              'text-slate-400 transition-transform ' +
              (isOpen ? 'rotate-180' : '')
            }
          />
        </button>
        {isOpen && <div className="px-3 pb-3">{children}</div>}
      </section>
    )
  }

  return (
    <section>
      <h2 className="mb-2 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-500">
        <Icon size={12} className="text-slate-400" />
        <span>{title}</span>
      </h2>
      {children}
    </section>
  )
}

export default App
