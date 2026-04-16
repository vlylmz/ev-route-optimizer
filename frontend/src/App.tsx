import { useMemo, useState } from 'react'
import { RouteForm } from './components/RouteForm'
import { MapView } from './components/MapView'
import { ReportPanel } from './components/ReportPanel'
import { useVehicles } from './hooks/useVehicles'
import { useOptimize } from './hooks/useOptimize'
import { useRoute } from './hooks/useRoute'
import type { OptimizeRequest } from './services/schemas'

function App() {
  const vehiclesQ = useVehicles()
  const optimizeM = useOptimize()
  const routeM = useRoute()

  const [submitted, setSubmitted] = useState<OptimizeRequest | null>(null)

  const handleSubmit = (req: OptimizeRequest) => {
    setSubmitted(req)
    optimizeM.mutate(req)
    routeM.mutate({ start: req.start, end: req.end })
  }

  const geometry = routeM.data?.geometry ?? []
  const stations = useMemo(
    () => (routeM.data?.stations as Array<Record<string, unknown>> | undefined) ?? [],
    [routeM.data],
  )

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">
            EV Route Optimizer
          </h1>
          <p className="text-sm text-slate-600">
            Rota + eğim + hava + istasyon verisi üzerinden 3 profilli enerji planı.
          </p>
        </div>
        <a
          href="http://127.0.0.1:8000/docs"
          target="_blank"
          rel="noreferrer"
          className="text-sm text-indigo-600 hover:underline"
        >
          API dokümanı →
        </a>
      </header>

      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <RouteForm
          vehicles={vehiclesQ.data ?? []}
          vehiclesLoading={vehiclesQ.isLoading}
          vehiclesError={vehiclesQ.isError}
          onSubmit={handleSubmit}
          isSubmitting={optimizeM.isPending || routeM.isPending}
        />

        <div className="flex flex-col gap-4">
          <MapView
            geometry={geometry}
            stations={stations as Parameters<typeof MapView>[0]['stations']}
            start={submitted?.start}
            end={submitted?.end}
          />

          {optimizeM.isPending && (
            <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-700">
              Rota optimize ediliyor — OSRM, eğim, hava ve istasyon verisi
              çekiliyor…
            </div>
          )}

          {optimizeM.isError && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              Hata: {optimizeM.error.message}
            </div>
          )}

          {optimizeM.data && <ReportPanel result={optimizeM.data} />}

          {!optimizeM.data && !optimizeM.isPending && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
              Soldan rota bilgilerini doldur ve "Rotayı Optimize Et" butonuna
              bas.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default App
