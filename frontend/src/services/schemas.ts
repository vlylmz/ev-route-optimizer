import { z } from 'zod'

/**
 * Zod şemaları — FastAPI (app/api/schemas.py) ile birebir uyumlu.
 * Backend tarafında değişiklik olursa burayı da güncelle.
 */

export const CoordinateSchema = z.object({
  lat: z.number().min(-90).max(90),
  lon: z.number().min(-180).max(180),
})
export type Coordinate = z.infer<typeof CoordinateSchema>

export const HealthResponseSchema = z.object({
  status: z.literal('ok'),
  service: z.string(),
  version: z.string(),
  model_available: z.boolean(),
  model_version: z.string().nullable().optional(),
  vehicle_count: z.number(),
})
export type HealthResponse = z.infer<typeof HealthResponseSchema>

export const VehicleSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  make: z.string(),
  model: z.string(),
  variant: z.string(),
  year: z.number(),
  body_type: z.string(),
  usable_battery_kwh: z.number(),
  ideal_consumption_wh_km: z.number(),
  wltp_range_km: z.number(),
  max_dc_charge_kw: z.number(),
})
export type VehicleSummary = z.infer<typeof VehicleSummarySchema>

export const VehicleDetailSchema = VehicleSummarySchema.extend({
  drivetrain: z.string(),
  battery_chemistry: z.string(),
  gross_battery_kwh: z.number(),
  soc_min_pct: z.number(),
  soc_max_pct: z.number(),
  regen_efficiency: z.number(),
  weight_kg: z.number(),
  max_ac_charge_kw: z.number(),
  temp_penalty_factor: z.number(),
  charge_curve_hint: z.string(),
  default_hvac_load_kw: z.number(),
})
export type VehicleDetail = z.infer<typeof VehicleDetailSchema>

export const StrategyNameSchema = z.enum(['fast', 'efficient', 'balanced'])
export type StrategyName = z.infer<typeof StrategyNameSchema>

export const RecommendedStopSchema = z.object({
  name: z.string(),
  distance_along_route_km: z.number(),
  detour_distance_km: z.number().default(0),
  detour_minutes: z.number().default(0),
  arrival_soc_percent: z.number().default(0),
  target_soc_percent: z.number().default(0),
  charge_minutes: z.number().default(0),
  power_kw: z.number().default(0),
})
export type RecommendedStop = z.infer<typeof RecommendedStopSchema>

export const ProfileCardSchema = z.object({
  key: StrategyNameSchema,
  label: z.string(),
  feasible: z.boolean(),
  total_energy_kwh: z.number().nullable().optional(),
  total_trip_minutes: z.number().nullable().optional(),
  charging_minutes: z.number().nullable().optional(),
  stop_count: z.number().nullable().optional(),
  final_soc_pct: z.number().nullable().optional(),
  used_ml: z.boolean(),
  model_version: z.string().nullable().optional(),
  recommended_stops: z.array(RecommendedStopSchema).default([]),
  raw: z.record(z.string(), z.unknown()).default({}),
})
export type ProfileCard = z.infer<typeof ProfileCardSchema>

export const OptimizeResponseSchema = z.object({
  status: z.string(),
  vehicle_id: z.string(),
  vehicle_name: z.string(),
  initial_soc_pct: z.number(),
  final_soc_pct: z.number(),
  total_distance_km: z.number(),
  total_energy_kwh: z.number(),
  used_ml: z.boolean(),
  ml_segment_count: z.number().default(0),
  heuristic_segment_count: z.number().default(0),
  model_version: z.string().nullable().optional(),
  recommended_profile: StrategyNameSchema.nullable().optional(),
  profiles: z.array(ProfileCardSchema),
  raw_optimization: z.record(z.string(), z.unknown()).default({}),
})
export type OptimizeResponse = z.infer<typeof OptimizeResponseSchema>

export const OptimizeRequestSchema = z.object({
  vehicle_id: z.string().min(1),
  start: CoordinateSchema,
  end: CoordinateSchema,
  initial_soc_pct: z.number().min(0).max(100),
  target_arrival_soc_pct: z.number().min(0).max(100).nullable().optional(),
  strategies: z.array(StrategyNameSchema).min(1),
  use_ml: z.boolean().default(false),
})
export type OptimizeRequest = z.infer<typeof OptimizeRequestSchema>

export const SpeedLimitSegmentSchema = z.object({
  start_index: z.number(),
  end_index: z.number(),
  maxspeed_kmh: z.number().nullable().optional(),
  highway: z.string().nullable().optional(),
})
export type SpeedLimitSegment = z.infer<typeof SpeedLimitSegmentSchema>

export const SpeedLimitsResponseSchema = z.object({
  segments: z.array(SpeedLimitSegmentSchema),
  source: z.string(),
  sampled_point_count: z.number().default(0),
})
export type SpeedLimitsResponse = z.infer<typeof SpeedLimitsResponseSchema>

export const SpeedLimitsRequestSchema = z.object({
  geometry: z.array(z.array(z.number())).min(2),
  sample_every_n_points: z.number().int().positive().default(20),
})
export type SpeedLimitsRequest = z.infer<typeof SpeedLimitsRequestSchema>

export const GeocodeResultItemSchema = z.object({
  display_name: z.string(),
  name: z.string(),
  lat: z.number(),
  lon: z.number(),
  type: z.string().nullable().optional(),
  importance: z.number().default(0),
  country_code: z.string().nullable().optional(),
})
export type GeocodeResultItem = z.infer<typeof GeocodeResultItemSchema>

export const GeocodeResponseSchema = z.object({
  query: z.string(),
  results: z.array(GeocodeResultItemSchema),
})
export type GeocodeResponse = z.infer<typeof GeocodeResponseSchema>

export const RouteResponseSchema = z.object({
  summary: z.object({
    distance_km: z.number(),
    duration_min: z.number(),
    geometry_point_count: z.number(),
    sampled_point_count: z.number(),
    weather_point_count: z.number(),
    station_count: z.number(),
    avg_temp_c: z.number().nullable().optional(),
    min_temp_c: z.number().nullable().optional(),
    max_temp_c: z.number().nullable().optional(),
    avg_grade_pct: z.number().nullable().optional(),
    max_uphill_grade_pct: z.number().nullable().optional(),
    max_downhill_grade_pct: z.number().nullable().optional(),
  }),
  geometry: z.array(z.array(z.number())),
  elevation_profile: z.array(z.record(z.string(), z.unknown())).default([]),
  slope_segments: z.array(z.record(z.string(), z.unknown())).default([]),
  weather: z.record(z.string(), z.unknown()).default({}),
  stations: z.array(z.record(z.string(), z.unknown())).default([]),
})
export type RouteResponse = z.infer<typeof RouteResponseSchema>
