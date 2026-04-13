import { useState, useCallback } from 'react'
import client from '../api/client'
import type { Episode, EpisodeUpdate } from '../types'

interface UseEpisodesReturn {
  episodes: Episode[]
  selectedEpisode: Episode | null
  loading: boolean
  error: string | null
  fetchEpisodes: () => Promise<void>
  selectEpisode: (index: number) => void
  updateEpisode: (index: number, grade: string | null, tags: string[]) => Promise<void>
}

export function useEpisodes(): UseEpisodesReturn {
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchEpisodes = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await client.get<Episode[]>('/episodes')
      setEpisodes(response.data)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch episodes'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [])

  const selectEpisode = useCallback((index: number) => {
    setEpisodes(prev => {
      const ep = prev.find(e => e.episode_index === index) ?? null
      setSelectedEpisode(ep)
      return prev
    })
  }, [])

  const updateEpisode = useCallback(async (index: number, grade: string | null, tags: string[]) => {
    const update: EpisodeUpdate = { grade, tags }
    const response = await client.patch<Episode>(`/episodes/${index}`, update)
    const updated = response.data
    setEpisodes(prev => prev.map(e => e.episode_index === index ? updated : e))
    setSelectedEpisode(prev => prev?.episode_index === index ? updated : prev)
  }, [])

  return { episodes, selectedEpisode, loading, error, fetchEpisodes, selectEpisode, updateEpisode }
}
