import { useEffect, useMemo, useState } from 'react'
import { RouteForm } from './components/RouteForm'
import { MapView } from './components/MapView'
import { ReportPanel } from './components/ReportPanel'
import {
  ReservationDialog,
  type Reservation,
} from './components/ReservationDialog'
import { useVehicles } from './hooks/useVehicles'
import { useOptimize } from './hooks/useOptimize'
import { useRoute } from './hooks/useRoute'
import { useSpeedLimits } from './hooks/useSpeedLimits'
import type {
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
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [navMode, setNavMode] = useState(false)
  const [activeProfileKey, setActiveProfileKey] = useState<string | null>(null)

  // Rezervasyon state'i: key = "<strategy>::<stopIdx>"
  const [reservations, setReservations] = useState<Record<string, Reservation>>(
    {},
  )
  const [activeReservation, setActiveReservation] = useState<{
    key: string
    stop: RecommendedStop
  } | null>(null)

  const handleSubmit = (req: OptimizeRequest) => {
    setSubmitted(req)
    setReservations({}) // yeni rota → eski rezervasyonları temizle
    setActiveProfileKey(null) // yeni rota → recommended profile otomatik aktif olur
    optimizeM.mutate(req)
    routeM.mutate({ start: req.start, end: req.end })
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
        reserved: !!reservations[key],
      }
    })
  }, [optimizeM.data, activeProfileKey, reservations])

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
        stations={stations as Parameters<typeof MapView>[0]['stations']}
        start={submitted?.start}
        end={submitted?.end}
        navigationMode={navMode}
        speedLimits={speedLimitsM.data?.segments ?? []}
        highlightedStops={activeProfileStops}
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
          {/* Gradient header */}
          <div className="relative overflow-hidden bg-gradient-to-br from-indigo-600 via-indigo-500 to-violet-600 px-6 pb-6 pt-5 text-white">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(255,255,255,0.18),transparent_60%)]" />
            <div className="relative flex items-start justify-between">
              <div>
                <div className="mb-1 inline-flex items-center gap-2 rounded-full bg-white/15 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider backdrop-blur">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
                  Faz 7 — 3D Navigasyon
                </div>
                <h1 className="text-xl font-bold tracking-tight">
                  EV Route Optimizer
                </h1>
                <p className="mt-0.5 text-xs text-indigo-100/90">
                  Rota · Enerji · Şarj Planı · Rezervasyon
                </p>
              </div>
              <button
                onClick={() => setSidebarOpen(false)}
                className="rounded-lg p-1.5 text-white/80 transition hover:bg-white/15 hover:text-white"
                aria-label="Kapat"
              >
                ✕
              </button>
            </div>
          </div>

          {/* İçerik */}
          <div className="flex-1 space-y-5 px-5 py-5">
            <Section title="Rota & Araç" icon="📍">
              <RouteForm
                vehicles={vehiclesQ.data ?? []}
                vehiclesLoading={vehiclesQ.isLoading}
                vehiclesError={vehiclesQ.isError}
                onSubmit={handleSubmit}
                isSubmitting={optimizeM.isPending || routeM.isPending}
              />
            </Section>

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
                className="group relative w-full overflow-hidden rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 py-3.5 text-sm font-bold text-white shadow-lg transition hover:shadow-xl active:scale-[0.99]"
              >
                <span className="absolute inset-0 bg-gradient-to-r from-emerald-400/0 via-white/20 to-emerald-400/0 opacity-0 transition group-hover:opacity-100" />
                <span className="relative flex items-center justify-center gap-2">
                  <span className="text-lg">🧭</span>
                  <span>Yola Çık · 3D Navigasyon</span>
                </span>
              </button>
            )}

            {geometry.length >= 2 && (
              <div className="flex items-center justify-between rounded-lg border border-slate-200/70 bg-white/60 px-3 py-2 text-xs text-slate-600 backdrop-blur">
                <span className="flex items-center gap-2">
                  <span>🚦</span>
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

            {optimizeM.data && (
              <Section title="Sonuç" icon="📊">
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
                <span className="text-2xl">⚡</span>
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
  icon,
  children,
}: {
  title: string
  icon: string
  children: React.ReactNode
}) {
  return (
    <section>
      <h2 className="mb-2 flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">
        <span aria-hidden>{icon}</span>
        <span>{title}</span>
      </h2>
      {children}
    </section>
  )
}

export default App
