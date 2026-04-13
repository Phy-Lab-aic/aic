import { useState, useCallback } from 'react'
import client from '../api/client'
import type { DatasetInfo } from '../types'

interface UseDatasetReturn {
  dataset: DatasetInfo | null
  loading: boolean
  error: string | null
  loadDataset: (path: string) => Promise<void>
}

export function useDataset(): UseDatasetReturn {
  const [dataset, setDataset] = useState<DatasetInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadDataset = useCallback(async (path: string) => {
    setLoading(true)
    setError(null)
    try {
      const response = await client.post<DatasetInfo>('/datasets/load', { path })
      setDataset(response.data)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load dataset'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [])

  return { dataset, loading, error, loadDataset }
}
