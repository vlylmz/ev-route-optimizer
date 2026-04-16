import { useMutation } from '@tanstack/react-query'
import { postOptimize } from '../services/api'
import type { OptimizeRequest, OptimizeResponse } from '../services/schemas'

export function useOptimize() {
  return useMutation<OptimizeResponse, Error, OptimizeRequest>({
    mutationFn: postOptimize,
  })
}
