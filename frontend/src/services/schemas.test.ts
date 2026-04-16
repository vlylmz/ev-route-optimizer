import { describe, expect, it } from 'vitest'
import {
  OptimizeRequestSchema,
  OptimizeResponseSchema,
  VehicleSummarySchema,
} from './schemas'

describe('zod schemas', () => {
  it('accepts valid VehicleSummary', () => {
    const result = VehicleSummarySchema.safeParse({
      id: 'x',
      name: 'X',
      make: 'M',
      model: 'M',
      variant: 'V',
      year: 2024,
      body_type: 'SUV',
      usable_battery_kwh: 60,
      ideal_consumption_wh_km: 160,
      wltp_range_km: 400,
      max_dc_charge_kw: 150,
    })
    expect(result.success).toBe(true)
  })

  it('rejects OptimizeRequest with empty strategies', () => {
    const result = OptimizeRequestSchema.safeParse({
      vehicle_id: 'x',
      start: { lat: 39, lon: 32 },
      end: { lat: 41, lon: 28 },
      initial_soc_pct: 80,
      strategies: [],
    })
    expect(result.success).toBe(false)
  })

  it('rejects OptimizeRequest with out-of-range coordinate', () => {
    const result = OptimizeRequestSchema.safeParse({
      vehicle_id: 'x',
      start: { lat: 200, lon: 32 },
      end: { lat: 41, lon: 28 },
      initial_soc_pct: 80,
      strategies: ['fast'],
    })
    expect(result.success).toBe(false)
  })

  it('accepts OptimizeResponse with all profiles', () => {
    const result = OptimizeResponseSchema.safeParse({
      status: 'ok',
      vehicle_id: 'x',
      vehicle_name: 'X',
      initial_soc_pct: 80,
      final_soc_pct: 30,
      total_distance_km: 120,
      total_energy_kwh: 25,
      used_ml: false,
      ml_segment_count: 0,
      heuristic_segment_count: 2,
      recommended_profile: 'balanced',
      profiles: [
        {
          key: 'balanced',
          label: 'Dengeli',
          feasible: true,
          total_energy_kwh: 25,
          total_trip_minutes: 120,
          charging_minutes: 0,
          stop_count: 0,
          final_soc_pct: 30,
          used_ml: false,
          raw: {},
        },
      ],
      raw_optimization: {},
    })
    expect(result.success).toBe(true)
  })
})
