import { useEffect, useMemo, useState } from 'react'
import {
  BarChart3,
  ChevronDown,
  Compass,
  Gauge,
  History,
  MapPin,
  Mountain,
  Sparkles,
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
import type {
  GeocodeResultItem,
  OptimizeRequest,
  RecommendedStop,
} from './services/schemas'

function reservationKey(strategyKey: string, idx: number): string {
  return `${strategyKey}::${idx}`
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
        finalSocPct={activeProfileFinalSoc ?? undefined}
        usableBatteryKwh={activeVehicle?.usable_battery_kwh}
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
