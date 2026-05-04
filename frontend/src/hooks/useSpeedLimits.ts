import { useMutation } from '@tanstack/react-query'
import { postSpeedLimits } from '../services/api'
import type { SpeedLimitsResponse } from '../services/schemas'

export function useSpeedLimits() {
  return useMutation<
    SpeedLimitsResponse,
    Error,
    { geometry: number[][]; sample_every_n_points?: number }
  >({
    mutationFn: postSpeedLimits,
  })
}
