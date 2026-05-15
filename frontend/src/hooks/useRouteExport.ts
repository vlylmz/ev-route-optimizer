import { useCallback } from 'react'
import type { MapRef } from 'react-map-gl/maplibre'
import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import type { RecommendedStop } from '../services/schemas'

export interface RouteExportMeta {
  vehicleName: string
  startLabel: string
  endLabel: string
  distanceKm: number
  durationMin: number
  initialSocPct: number
  finalSocPct?: number | null
  strategyLabel: string
}

export interface RouteExportInput {
  mapRef: React.RefObject<MapRef | null>
  stops: RecommendedStop[]
  meta: RouteExportMeta
}

function captureMapPng(
  mapRef: RouteExportInput['mapRef'],
): string | null {
  const map = mapRef.current?.getMap()
  if (!map) return null
  // preserveDrawingBuffer aktif degilse canvas okunur ama bos gelebilir.
  // MapView'da bu flag aciktir.
  map.triggerRepaint()
  try {
    return map.getCanvas().toDataURL('image/png')
  } catch {
    return null
  }
}

function downloadDataUrl(dataUrl: string, filename: string) {
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function timestampSuffix(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(
    d.getHours(),
  )}${pad(d.getMinutes())}`
}

export function useRouteExport() {
  const exportPng = useCallback((input: RouteExportInput) => {
    const dataUrl = captureMapPng(input.mapRef)
    if (!dataUrl) {
      // eslint-disable-next-line no-console
      console.warn('Harita canvas yakalanamadi')
      return
    }
    downloadDataUrl(dataUrl, `rota-${timestampSuffix()}.png`)
  }, [])

  const exportPdf = useCallback((input: RouteExportInput) => {
    const dataUrl = captureMapPng(input.mapRef)
    const doc = new jsPDF({
      orientation: 'landscape',
      unit: 'mm',
      format: 'a4',
    })
    const { meta, stops } = input

    doc.setFontSize(16)
    doc.text('EV Rota Plani', 14, 15)
    doc.setFontSize(10)
    doc.text(
      [
        `Arac: ${meta.vehicleName}`,
        `${meta.startLabel}  ->  ${meta.endLabel}`,
        `Mesafe: ${meta.distanceKm.toFixed(1)} km  ·  Sure: ${meta.durationMin.toFixed(0)} dk`,
        `Strateji: ${meta.strategyLabel}`,
        `SoC: %${meta.initialSocPct.toFixed(0)} -> %${(meta.finalSocPct ?? 0).toFixed(0)}`,
      ],
      14,
      22,
    )

    let tableStartY = 50
    if (dataUrl) {
      // A4 yatay 297×210mm; sol margin 14, ust 50, max yukseklik ~115mm
      doc.addImage(dataUrl, 'PNG', 14, 50, 180, 110)
      tableStartY = 165
    }

    autoTable(doc, {
      startY: tableStartY,
      head: [['#', 'Istasyon', 'km', 'Varis %', 'Hedef %', 'kW', 'Sure dk']],
      body: stops.map((s, i) => [
        i + 1,
        s.name,
        s.distance_along_route_km.toFixed(1),
        s.arrival_soc_percent.toFixed(0),
        s.target_soc_percent.toFixed(0),
        s.power_kw.toFixed(0),
        s.charge_minutes.toFixed(0),
      ]),
      styles: { fontSize: 8 },
      headStyles: { fillColor: [79, 70, 229] }, // indigo-600
    })

    doc.save(`rota-${timestampSuffix()}.pdf`)
  }, [])

  return { exportPng, exportPdf }
}
