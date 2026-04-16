import { useQuery } from '@tanstack/react-query'
import { listVehicles } from '../services/api'

export function useVehicles() {
  return useQuery({
    queryKey: ['vehicles'],
    queryFn: listVehicles,
    staleTime: 5 * 60_000,
  })
}
