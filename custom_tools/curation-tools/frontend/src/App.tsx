import { useState, useCallback, useEffect, useRef } from 'react'
import { DatasetLoader } from './components/DatasetLoader'
import { EpisodeList } from './components/EpisodeList'
import { EpisodeEditor } from './components/EpisodeEditor'
import { TaskEditor } from './components/TaskEditor'
import { VideoPlayer, type VideoPlayerHandle } from './components/VideoPlayer'
import { ScalarChart } from './components/ScalarChart'
import { HubSync } from './components/HubSync'
import { SplitMergePanel } from './components/SplitMergePanel'
import { useEpisodes } from './hooks/useEpisodes'
import { GRADES } from './types'
import type { DatasetInfo, Episode } from './types'
import './App.css'

const GRADE_KEYS: Record<string, string> = {
  '1': 'Good', '2': 'Normal', '3': 'Bad',
}

type RightTab = 'details' | 'splitmerge'

export default function App() {
  const [dataset, setDataset] = useState<DatasetInfo | null>(null)
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null)
  const [currentFrame, setCurrentFrame] = useState(0)
  const [rightTab, setRightTab] = useState<RightTab>('details')
  const videoRef = useRef<VideoPlayerHandle>(null)
  const { episodes, loading: episodesLoading, error: episodesError, fetchEpisodes, updateEpisode } = useEpisodes()

  const handleDatasetLoaded = useCallback((ds: DatasetInfo) => {
    setDataset(ds)
    setSelectedEpisode(null)
    void fetchEpisodes()
  }, [fetchEpisodes])

  const handleEpisodeSelect = useCallback((episode: Episode) => {
    setSelectedEpisode(episode)
  }, [])

  const handleSaveEpisode = useCallback(async (index: number, grade: string | null, tags: string[]) => {
    await updateEpisode(index, grade, tags)
    // Auto-advance to next ungraded episode after grading
    if (grade) {
      const currentIdx = episodes.findIndex(e => e.episode_index === index)
      // Look forward first (skip the episode we just graded)
      let nextUngraded = episodes.find((e, i) => i > currentIdx && !e.grade)
      // Wrap around if needed
      if (!nextUngraded) {
        nextUngraded = episodes.find((e, i) => i < currentIdx && !e.grade)
      }
      if (nextUngraded) {
        setSelectedEpisode(nextUngraded)
        return
      }
    }
    setSelectedEpisode(prev =>
      prev?.episode_index === index ? { ...prev, grade, tags } : prev
    )
  }, [updateEpisode, episodes])

  // Navigate to adjacent episode
  const navigateEpisode = useCallback((direction: -1 | 1) => {
    if (!selectedEpisode || episodes.length === 0) return
    const idx = episodes.findIndex(e => e.episode_index === selectedEpisode.episode_index)
    const nextIdx = idx + direction
    if (nextIdx >= 0 && nextIdx < episodes.length) {
      const next = episodes[nextIdx]
      setSelectedEpisode(next)
    }
  }, [selectedEpisode, episodes])

  // Quick grade with keyboard
  const quickGrade = useCallback(async (gradeKey: string) => {
    if (!selectedEpisode) return
    const grade = GRADE_KEYS[gradeKey]
    if (!grade) return
    await handleSaveEpisode(selectedEpisode.episode_index, grade, selectedEpisode.tags)
  }, [selectedEpisode, handleSaveEpisode])

  // Global keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Skip if user is typing in an input
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      switch (e.key) {
        case 'ArrowUp':
        case 'k':
          e.preventDefault()
          navigateEpisode(-1)
          break
        case 'ArrowDown':
        case 'j':
          e.preventDefault()
          navigateEpisode(1)
          break
        case 'ArrowLeft':
          e.preventDefault()
          videoRef.current?.stepFrame(-1)
          break
        case 'ArrowRight':
          e.preventDefault()
          videoRef.current?.stepFrame(1)
          break
        case '1': case '2': case '3':
          e.preventDefault()
          quickGrade(e.key)
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigateEpisode, quickGrade])

  // Progress stats
  const totalEpisodes = episodes.length
  const gradedCount = episodes.filter(e => e.grade).length
  const progressPct = totalEpisodes > 0 ? (gradedCount / totalEpisodes) * 100 : 0

  return (
    <div className="app-layout">
      {/* Left sidebar */}
      <aside className="sidebar">
        <DatasetLoader onDatasetLoaded={handleDatasetLoaded} />
        <HubSync />

        {dataset && (
          <div className="progress-bar-container">
            <div className="progress-info">
              <span className="progress-label">Progress</span>
              <span className="progress-count">{gradedCount} / {totalEpisodes}</span>
            </div>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        )}

        <EpisodeList
          episodes={episodes}
          loading={episodesLoading}
          error={episodesError}
          onEpisodeSelect={handleEpisodeSelect}
          selectedIndex={selectedEpisode?.episode_index ?? null}
        />
      </aside>

      {/* Center: video + grading overlay */}
      <main className="center-panel">
        <VideoPlayer
          ref={videoRef}
          episodeIndex={selectedEpisode?.episode_index ?? null}
          fps={dataset?.fps ?? 30}
          onFrameChange={setCurrentFrame}
        />

        {/* Quick grade bar below video */}
        {selectedEpisode && (
          <div className="quick-grade-bar">
            <span className="quick-grade-label">Grade:</span>
            {GRADES.map((g, i) => (
              <button
                key={g}
                className={`grade-btn grade-${g} ${selectedEpisode.grade === g ? 'active' : ''}`}
                onClick={() => handleSaveEpisode(selectedEpisode.episode_index, g, selectedEpisode.tags)}
                title={`Press ${i + 1}`}
              >
                <span className="grade-letter">{g}</span>
                <span className="grade-key">{i + 1}</span>
              </button>
            ))}
            <div className="nav-hint">
              <kbd>&uarr;</kbd><kbd>&darr;</kbd> episode
              <kbd>&larr;</kbd><kbd>&rarr;</kbd> frame
            </div>
          </div>
        )}
      </main>

      {/* Right panel */}
      <aside className="right-panel">
        {/* Tab bar */}
        <div className="main-tab-bar" role="tablist">
          <button
            role="tab"
            aria-selected={rightTab === 'details'}
            className={`main-tab-btn${rightTab === 'details' ? ' active' : ''}`}
            onClick={() => setRightTab('details')}
          >
            Details
          </button>
          <button
            role="tab"
            aria-selected={rightTab === 'splitmerge'}
            className={`main-tab-btn${rightTab === 'splitmerge' ? ' active' : ''}`}
            onClick={() => setRightTab('splitmerge')}
          >
            Split / Merge
          </button>
        </div>

        {rightTab === 'details' && (
          <>
            <EpisodeEditor
              episode={selectedEpisode}
              onSave={handleSaveEpisode}
            />
            <TaskEditor episode={selectedEpisode} />
            <ScalarChart
              episodeIndex={selectedEpisode?.episode_index ?? null}
              currentFrame={currentFrame}
            />
          </>
        )}

        {rightTab === 'splitmerge' && (
          <div className="split-merge-main">
            <SplitMergePanel datasetPath={dataset?.path ?? null} episodes={episodes} />
          </div>
        )}
      </aside>
    </div>
  )
}
