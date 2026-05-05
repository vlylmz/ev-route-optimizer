import axios, { AxiosError } from 'axios'
import {
  CompareVehiclesResponseSchema,
  GeocodeResponseSchema,
  HealthResponseSchema,
  OptimizeRequestSchema,
  OptimizeResponseSchema,
  RouteResponseSchema,
  SpeedLimitsResponseSchema,
  VehicleDetailSchema,
  VehicleSummarySchema,
  type CompareVehiclesRequest,
  type CompareVehiclesResponse,
  type GeocodeResponse,
  type HealthResponse,
  type OptimizeRequest,
  type OptimizeResponse,
  type RouteResponse,
  type SpeedLimitsResponse,
  type VehicleDetail,
  type VehicleSummary,
} from './schemas'
import { z } from 'zod'

/**
 * Dev'de Vite proxy kullanıyoruz (vite.config.ts).
 * Prod'da VITE_API_BASE_URL ile override edilebilir.
 */
const baseURL = import.meta.env.VITE_API_BASE_URL ?? '/api'

export const api = axios.create({
  baseURL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

export class ApiError extends Error {
  public readonly status: number | undefined
  public readonly detail: unknown

  constructor(message: string, status?: number, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

function rethrow(err: unknown): never {
  if (err instanceof AxiosError) {
    const detail = err.response?.data
    const message =
      (typeof detail === 'object' && detail && 'detail' in detail
        ? String((detail as Record<string, unknown>).detail)
        : err.message) || 'API isteği başarısız oldu.'
    throw new ApiError(message, err.response?.status, detail)
  }
  if (err instanceof z.ZodError) {
    throw new ApiError(`Geçersiz API yanıtı: ${err.message}`, 0, err.issues)
  }
  throw err
}

export async function getHealth(): Promise<HealthResponse> {
  try {
    const res = await api.get('/health')
    return HealthResponseSchema.parse(res.data)
  } catch (err) {
    rethrow(err)
  }
}

export async function listVehicles(): Promise<VehicleSummary[]> {
  try {
    const res = await api.get('/vehicles')
    return z.array(VehicleSummarySchema).parse(res.data)
  } catch (err) {
    rethrow(err)
  }
}

export async function getVehicle(id: string): Promise<VehicleDetail> {
  try {
    const res = await api.get(`/vehicles/${encodeURIComponent(id)}`)
    return VehicleDetailSchema.parse(res.data)
  } catch (err) {
    rethrow(err)
  }
}

export async function postRoute(body: {
  start: { lat: number; lon: number }
  end: { lat: number; lon: number }
}): Promise<RouteResponse> {
  try {
    const res = await api.post('/route', body)
    return RouteResponseSchema.parse(res.data)
  } catch (err) {
    rethrow(err)
  }
}

export async function postOptimize(
  input: OptimizeRequest,
): Promise<OptimizeResponse> {
  try {
    const body = OptimizeRequestSchema.parse(input)
    const res = await api.post('/optimize', body)
    return OptimizeResponseSchema.parse(res.data)
  } catch (err) {
    rethrow(err)
  }
}

export async function postSpeedLimits(body: {
  geometry: number[][]
  sample_every_n_points?: number
}): Promise<SpeedLimitsResponse> {
  try {
    const res = await api.post('/speed-limits', {
      geometry: body.geometry,
      sample_every_n_points: body.sample_every_n_points ?? 20,
    })
    return SpeedLimitsResponseSchema.parse(res.data)
  } catch (err) {
    rethrow(err)
  }
}

export async function getGeocode(
  q: string,
  limit = 5,
): Promise<GeocodeResponse> {
  try {
    const res = await api.get('/geocode', { params: { q, limit } })
    return GeocodeResponseSchema.parse(res.data)
  } catch (err) {
    rethrow(err)
  }
}

export async function postCompareVehicles(
  body: CompareVehiclesRequest,
): Promise<CompareVehiclesResponse> {
  try {
    const res = await api.post('/compare-vehicles', body)
    return CompareVehiclesResponseSchema.parse(res.data)
  } catch (err) {
    rethrow(err)
  }
}
