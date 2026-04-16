import { useEffect } from 'react'
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import L from 'leaflet'
import type { LatLngExpression, LatLngBoundsExpression } from 'leaflet'

// Leaflet default marker asset fix for Vite bundling
import iconUrl from 'leaflet/dist/images/marker-icon.png'
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png'
import shadowUrl from 'leaflet/dist/images/marker-shadow.png'

L.Icon.Default.mergeOptions({
  iconUrl,
  iconRetinaUrl,
  shadowUrl,
})

const chargingIcon = new L.DivIcon({
  className: '',
  html: '<div style="background:#10b981;width:16px;height:16px;border-radius:50%;border:2px solid white;box-shadow:0 2px 4px rgba(0,0,0,0.3)"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
})

interface Station {
  ocm_id?: number
  name?: string
  latitude?: number
  longitude?: number
  power_kw?: number
  distance_from_route_km?: number
}

interface Props {
  geometry: number[][]
  stations: Station[]
  start?: { lat: number; lon: number }
  end?: { lat: number; lon: number }
}

const ANKARA: LatLngExpression = [39.92, 32.85]

export function MapView({ geometry, stations, start, end }: Props) {
  const hasRoute = geometry.length > 1
  const center: LatLngExpression = start
    ? [start.lat, start.lon]
    : hasRoute
    ? [geometry[0][0], geometry[0][1]]
    : ANKARA

  const polylinePositions: LatLngExpression[] = geometry.map(([lat, lon]) => [lat, lon])

  const bounds: LatLngBoundsExpression | null = hasRoute
    ? (polylinePositions as [number, number][])
    : null

  return (
    <div className="h-[500px] w-full overflow-hidden rounded-xl border border-slate-200 shadow-sm">
      <MapContainer center={center} zoom={6} className="h-full w-full">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {hasRoute && (
          <Polyline
            positions={polylinePositions}
            pathOptions={{ color: '#4f46e5', weight: 5, opacity: 0.85 }}
          />
        )}

        {start && (
          <Marker position={[start.lat, start.lon]}>
            <Popup>Başlangıç</Popup>
          </Marker>
        )}
        {end && (
          <Marker position={[end.lat, end.lon]}>
            <Popup>Varış</Popup>
          </Marker>
        )}

        {stations.map((s, idx) => {
          if (s.latitude == null || s.longitude == null) return null
          return (
            <Marker
              key={s.ocm_id ?? idx}
              position={[s.latitude, s.longitude]}
              icon={chargingIcon}
            >
              <Popup>
                <div className="text-sm">
                  <div className="font-semibold">{s.name ?? 'İstasyon'}</div>
                  {s.power_kw != null && <div>{s.power_kw} kW DC</div>}
                  {s.distance_from_route_km != null && (
                    <div className="text-xs text-slate-500">
                      Rotadan sapma: {s.distance_from_route_km.toFixed(2)} km
                    </div>
                  )}
                </div>
              </Popup>
            </Marker>
          )
        })}

        {bounds && <FitBounds bounds={bounds} />}
      </MapContainer>
    </div>
  )
}

function FitBounds({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap()
  useEffect(() => {
    map.fitBounds(bounds, { padding: [30, 30] })
  }, [bounds, map])
  return null
}
