import { useMutation } from '@tanstack/react-query'
import { postRoute } from '../services/api'
import type { RouteResponse } from '../services/schemas'

export function useRoute() {
  return useMutation<
    RouteResponse,
    Error,
    { start: { lat: number; lon: number }; end: { lat: number; lon: number } }
  >({
    mutationFn: postRoute,
  })
}
