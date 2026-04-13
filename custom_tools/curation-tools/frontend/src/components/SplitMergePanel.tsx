import { useState, useEffect, useCallback } from 'react'
import client from '../api/client'
import type { Episode } from '../types/index'

interface SplitMergePanelProps {
  datasetPath: string | null
  episodes: Episode[]
}

interface JobStatus {
  job_id: string
  operation: string
  status: string
  created_at: string
  completed_at: string | null
  error: string | null
  result_path: string | null
}

type TabId = 'split' | 'merge'

function useJobPoller() {
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null)
  const [polling, setPolling] = useState(false)

  const startPolling = useCallback((jobId: string) => {
    setPolling(true)
    setJobStatus(null)

    const interval = setInterval(async () => {
      try {
        const resp = await client.get<JobStatus>(`/datasets/ops/status/${jobId}`)
        const s = resp.data
        setJobStatus(s)
        if (s.status === 'completed' || s.status === 'failed') {
          clearInterval(interval)
          setPolling(false)
        }
      } catch {
        clearInterval(interval)
        setPolling(false)
      }
    }, 1000)

    return () => clearInterval(interval)
  }, [])

  const reset = useCallback(() => {
    setJobStatus(null)
    setPolling(false)
  }, [])

  return { jobStatus, polling, startPolling, reset }
}

function JobProgress({ jobStatus, polling }: { jobStatus: JobStatus | null; polling: boolean }) {
  if (!jobStatus && !polling) return null

  if (polling && !jobStatus) {
    return <div style={s.statusBox}>Running...</div>
  }

  if (!jobStatus) return null

  const isOk = jobStatus.status === 'completed'
  const isFail = jobStatus.status === 'failed'

  return (
    <div style={{ ...s.statusBox, borderColor: isOk ? '#4caf50' : isFail ? '#e05252' : '#3a6ea5' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color: isOk ? '#4caf50' : isFail ? '#e05252' : '#aaa', fontSize: 12, fontWeight: 600 }}>
          {jobStatus.status.toUpperCase()}
        </span>
        {polling && <span style={s.spinner}>⟳</span>}
      </div>
      {isOk && jobStatus.result_path && (
        <div style={s.resultPath}>
          Result: <span style={{ fontFamily: 'monospace', color: '#c8e6c9' }}>{jobStatus.result_path}</span>
        </div>
      )}
      {isFail && jobStatus.error && (
        <div style={s.errorText}>{jobStatus.error}</div>
      )}
    </div>
  )
}

type SplitMode = 'grade' | 'tag'
type SplitDestination = 'new' | 'existing'

const GRADE_OPTIONS = ['Good', 'Normal', 'Bad', 'Ungraded'] as const

function formatEpisodeRanges(indices: number[]): string {
  if (indices.length === 0) return 'none'
  const sorted = [...indices].sort((a, b) => a - b)
  const ranges: string[] = []
  let start = sorted[0]
  let end = sorted[0]
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === end + 1) {
      end = sorted[i]
    } else {
      ranges.push(start === end ? `${start}` : `${start}-${end}`)
      start = sorted[i]
      end = sorted[i]
    }
  }
  ranges.push(start === end ? `${start}` : `${start}-${end}`)
  return `Episodes: ${ranges.join(', ')}`
}

function SplitTab({
  datasetPath,
  episodes,
}: {
  datasetPath: string | null
  episodes: Episode[]
}) {
  const [splitMode, setSplitMode] = useState<SplitMode>('grade')
  const [selectedGrades, setSelectedGrades] = useState<Set<string>>(new Set())
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())
  const [targetName, setTargetName] = useState('')
  const [destination, setDestination] = useState<SplitDestination>('new')
  const [availableDatasets, setAvailableDatasets] = useState<{ name: string; path: string }[]>([])
  const [loadingDatasets, setLoadingDatasets] = useState(false)
  const [selectedTargetPath, setSelectedTargetPath] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { jobStatus, polling, startPolling, reset } = useJobPoller()

  const fetchAvailableDatasets = useCallback(async () => {
    setLoadingDatasets(true)
    try {
      const resp = await client.get<{ name: string; path: string }[]>('/datasets/list')
      setAvailableDatasets(resp.data)
    } catch {
      setAvailableDatasets([])
    } finally {
      setLoadingDatasets(false)
    }
  }, [])

  useEffect(() => {
    if (destination === 'existing') {
      void fetchAvailableDatasets()
    }
  }, [destination, fetchAvailableDatasets])

  const allTags = Array.from(new Set(episodes.flatMap(e => e.tags ?? []))).sort()

  const matchingEpisodes = splitMode === 'grade'
    ? episodes.filter(e => selectedGrades.has(e.grade ?? 'Ungraded'))
    : episodes.filter(e => (e.tags ?? []).some(t => selectedTags.has(t)))

  const toggleGrade = (grade: string) => {
    setSelectedGrades(prev => {
      const next = new Set(prev)
      if (next.has(grade)) next.delete(grade)
      else next.add(grade)
      return next
    })
  }

  const toggleTag = (tag: string) => {
    setSelectedTags(prev => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }

  const handleSubmit = async () => {
    if (!datasetPath) return
    if (matchingEpisodes.length === 0) { setSubmitError('No episodes match the selected filter'); return }

    if (destination === 'new') {
      if (!targetName.trim()) { setSubmitError('Enter a target dataset name'); return }
    } else {
      if (!selectedTargetPath) { setSubmitError('Select a target dataset'); return }
    }

    setSubmitting(true)
    setSubmitError(null)
    reset()

    try {
      const episodeIds = matchingEpisodes.map(e => e.episode_index).sort((a, b) => a - b)

      if (destination === 'new') {
        const resp = await client.post<{ job_id: string; operation: string; status: string }>('/datasets/split-into', {
          source_path: datasetPath,
          episode_ids: episodeIds,
          target_name: targetName.trim(),
        })
        startPolling(resp.data.job_id)
      } else {
        const targetDs = availableDatasets.find(ds => ds.path === selectedTargetPath)
        const resp = await client.post<{ job_id: string; operation: string; status: string }>('/datasets/split-into', {
          source_path: datasetPath,
          episode_ids: episodeIds,
          target_name: targetDs?.name ?? 'merged',
          target_path: selectedTargetPath,
        })
        startPolling(resp.data.job_id)
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Split failed'
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (!datasetPath) {
    return <div style={s.emptyState}>Load a dataset first to split episodes.</div>
  }

  return (
    <div style={s.tabContent}>
      {/* Split mode toggle */}
      <div style={s.fieldLabel}>Split By</div>
      <div style={s.modeToggle}>
        {(['grade', 'tag'] as SplitMode[]).map(mode => (
          <button
            key={mode}
            style={{ ...s.modeBtn, ...(splitMode === mode ? s.modeBtnActive : {}) }}
            onClick={() => setSplitMode(mode)}
          >
            {mode === 'grade' ? 'Grade' : 'Tag'}
          </button>
        ))}
      </div>

      {/* Grade filter */}
      {splitMode === 'grade' && (
        <>
          <div style={s.fieldLabel}>Select grades</div>
          <div style={s.chipRow}>
            {GRADE_OPTIONS.map(grade => {
              const active = selectedGrades.has(grade)
              const color = grade === 'Good' ? '#4caf50' : grade === 'Bad' ? '#f44336' : grade === 'Normal' ? '#ffc107' : '#888'
              return (
                <button
                  key={grade}
                  style={{
                    ...s.chip,
                    borderColor: active ? color : '#333',
                    color: active ? color : '#666',
                    background: active ? `${color}18` : 'transparent',
                  }}
                  onClick={() => toggleGrade(grade)}
                >
                  {grade}
                </button>
              )
            })}
          </div>
        </>
      )}

      {/* Tag filter */}
      {splitMode === 'tag' && (
        <>
          <div style={s.fieldLabel}>Select tags</div>
          {allTags.length === 0 ? (
            <div style={s.empty}>No tags found in this dataset.</div>
          ) : (
            <div style={s.chipRow}>
              {allTags.map(tag => {
                const active = selectedTags.has(tag)
                return (
                  <button
                    key={tag}
                    style={{
                      ...s.chip,
                      borderColor: active ? '#3a6ea5' : '#333',
                      color: active ? '#c0d8f0' : '#666',
                      background: active ? '#3a6ea518' : 'transparent',
                    }}
                    onClick={() => toggleTag(tag)}
                  >
                    {tag}
                  </button>
                )
              })}
            </div>
          )}
        </>
      )}

      {/* Match preview */}
      <div style={s.matchPreview}>
        <span style={{ color: matchingEpisodes.length > 0 ? '#c0d8f0' : '#555' }}>
          {matchingEpisodes.length} episode{matchingEpisodes.length !== 1 ? 's' : ''} match
        </span>
        {matchingEpisodes.length > 0 && (
          <div style={s.matchRanges}>
            {formatEpisodeRanges(matchingEpisodes.map(e => e.episode_index))}
          </div>
        )}
      </div>

      {/* Destination toggle */}
      <div style={s.fieldLabel}>Destination</div>
      <div style={s.modeToggle}>
        {(['new', 'existing'] as SplitDestination[]).map(mode => (
          <button
            key={mode}
            style={{ ...s.modeBtn, ...(destination === mode ? s.modeBtnActive : {}) }}
            onClick={() => setDestination(mode)}
          >
            {mode === 'new' ? 'New Dataset' : 'Existing Dataset'}
          </button>
        ))}
      </div>

      {destination === 'new' ? (
        <>
          <div style={s.fieldLabel}>Target dataset name</div>
          <input
            style={s.textInput}
            type="text"
            placeholder="e.g. my_dataset_split"
            value={targetName}
            onChange={e => setTargetName(e.target.value)}
            disabled={submitting || polling}
          />
        </>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <div style={s.fieldLabel}>Target dataset</div>
            <button style={s.refreshBtn} onClick={fetchAvailableDatasets} disabled={loadingDatasets}>
              {loadingDatasets ? '...' : 'Refresh'}
            </button>
          </div>
          {availableDatasets.length === 0 && !loadingDatasets ? (
            <div style={s.empty}>No datasets available.</div>
          ) : (
            <select
              style={{ ...s.textInput, cursor: 'pointer' }}
              value={selectedTargetPath}
              onChange={e => setSelectedTargetPath(e.target.value)}
              disabled={submitting || polling || loadingDatasets}
            >
              <option value="">-- Select a dataset --</option>
              {availableDatasets.map(ds => (
                <option key={ds.path} value={ds.path}>{ds.name}</option>
              ))}
            </select>
          )}
        </>
      )}

      {submitError && <div style={s.errorText}>{submitError}</div>}

      <button
        style={{ ...s.actionBtn, opacity: submitting || polling ? 0.6 : 1 }}
        onClick={handleSubmit}
        disabled={submitting || polling}
      >
        {submitting ? 'Submitting...' : destination === 'new' ? 'Split Dataset' : 'Split & Merge Into'}
      </button>

      <JobProgress jobStatus={jobStatus} polling={polling} />
    </div>
  )
}

function MergeTab() {
  const [availableDatasets, setAvailableDatasets] = useState<{ name: string; path: string }[]>([])
  const [loadingDatasets, setLoadingDatasets] = useState(false)
  const [datasetsError, setDatasetsError] = useState<string | null>(null)
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set())
  const [targetName, setTargetName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { jobStatus, polling, startPolling, reset } = useJobPoller()

  const fetchDatasets = useCallback(async () => {
    setLoadingDatasets(true)
    setDatasetsError(null)
    try {
      // Fetch available datasets list
      const resp = await client.get<{ name: string; path: string }[]>('/datasets/list')
      setAvailableDatasets(resp.data)
    } catch {
      setDatasetsError('Failed to load datasets')
    } finally {
      setLoadingDatasets(false)
    }
  }, [])

  useEffect(() => {
    void fetchDatasets()
  }, [fetchDatasets])

  const toggleDataset = (path: string) => {
    setSelectedPaths(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const handleSubmit = async () => {
    if (selectedPaths.size < 2) { setSubmitError('Select at least 2 datasets'); return }
    if (!targetName.trim()) { setSubmitError('Enter a target dataset name'); return }

    setSubmitting(true)
    setSubmitError(null)
    reset()

    try {
      const resp = await client.post<{ job_id: string; operation: string; status: string }>('/datasets/merge', {
        source_paths: Array.from(selectedPaths),
        target_name: targetName.trim(),
      })
      startPolling(resp.data.job_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Merge failed'
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={s.tabContent}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <div style={s.fieldLabel}>
          Datasets ({selectedPaths.size} selected)
        </div>
        <button style={s.refreshBtn} onClick={fetchDatasets} disabled={loadingDatasets}>
          {loadingDatasets ? '...' : 'Refresh'}
        </button>
      </div>

      {datasetsError && <div style={s.errorText}>{datasetsError}</div>}

      <div style={s.episodeList}>
        {loadingDatasets && <div style={s.empty}>Loading...</div>}
        {!loadingDatasets && availableDatasets.length === 0 && (
          <div style={s.emptyState}>No datasets available for merge. Mount datasets via Hub Sync first.</div>
        )}
        {availableDatasets.map(ds => (
          <label key={ds.path} style={s.checkRow}>
            <input
              type="checkbox"
              checked={selectedPaths.has(ds.path)}
              onChange={() => toggleDataset(ds.path)}
              style={s.checkbox}
            />
            <span style={s.epLabel}>
              <span style={{ ...s.epIndex, color: '#c0d8f0' }}>{ds.name}</span>
              <span style={s.epTask}>{ds.path}</span>
            </span>
          </label>
        ))}
      </div>

      <div style={s.fieldLabel}>Target dataset name</div>
      <input
        style={s.textInput}
        type="text"
        placeholder="e.g. merged_dataset"
        value={targetName}
        onChange={e => setTargetName(e.target.value)}
        disabled={submitting || polling}
      />

      {submitError && <div style={s.errorText}>{submitError}</div>}

      <button
        style={{ ...s.actionBtn, opacity: submitting || polling ? 0.6 : 1 }}
        onClick={handleSubmit}
        disabled={submitting || polling}
      >
        {submitting ? 'Submitting...' : 'Merge Datasets'}
      </button>

      <JobProgress jobStatus={jobStatus} polling={polling} />
    </div>
  )
}

export function SplitMergePanel({ datasetPath, episodes }: SplitMergePanelProps) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<TabId>('split')

  return (
    <div style={s.container}>
      <button style={s.header} onClick={() => setOpen(v => !v)} aria-expanded={open} aria-label="Split / Merge panel">
        <span style={s.headerTitle}>Split / Merge</span>
        <span style={s.chevron}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={s.body}>
          <div style={s.tabs}>
            {(['split', 'merge'] as TabId[]).map(t => (
              <button
                key={t}
                style={{ ...s.tabBtn, ...(tab === t ? s.tabBtnActive : {}) }}
                onClick={() => setTab(t)}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>

          {tab === 'split' && <SplitTab datasetPath={datasetPath} episodes={episodes} />}
          {tab === 'merge' && <MergeTab />}
        </div>
      )}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: {
    borderBottom: '1px solid #333',
  },
  header: {
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 12px',
    background: 'transparent',
    border: 'none',
    color: '#e0e0e0',
    cursor: 'pointer',
    textAlign: 'left',
  },
  headerTitle: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
    color: '#888',
  },
  chevron: {
    fontSize: 10,
    color: '#555',
  },
  body: {
    padding: '0 12px 12px',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 8,
  },
  tabs: {
    display: 'flex',
    gap: 4,
    borderBottom: '1px solid #2a2a2a',
    paddingBottom: 6,
  },
  tabBtn: {
    background: 'transparent',
    border: 'none',
    color: '#666',
    fontSize: 12,
    padding: '4px 10px',
    cursor: 'pointer',
    borderRadius: '3px 3px 0 0',
  },
  tabBtnActive: {
    color: '#c0d8f0',
    background: '#2a2a2a',
  },
  tabContent: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 8,
  },
  fieldLabel: {
    fontSize: 11,
    color: '#888',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  selectAllBtn: {
    background: 'transparent',
    border: '1px solid #333',
    borderRadius: 3,
    color: '#888',
    fontSize: 10,
    padding: '2px 6px',
    cursor: 'pointer',
  },
  modeToggle: {
    display: 'flex',
    gap: 4,
  },
  modeBtn: {
    background: 'transparent',
    border: '1px solid #333',
    borderRadius: 4,
    color: '#666',
    fontSize: 12,
    padding: '4px 12px',
    cursor: 'pointer',
  },
  modeBtnActive: {
    background: '#2a3a4a',
    border: '1px solid #3a6ea5',
    color: '#c0d8f0',
  },
  chipRow: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: 6,
  },
  chip: {
    background: 'transparent',
    border: '1px solid #333',
    borderRadius: 12,
    fontSize: 11,
    fontWeight: 600,
    padding: '3px 10px',
    cursor: 'pointer',
    transition: 'all 0.1s',
  },
  matchPreview: {
    background: '#1a1a1a',
    border: '1px solid #2a2a2a',
    borderRadius: 4,
    padding: '8px 10px',
    fontSize: 12,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
  },
  matchRanges: {
    fontSize: 11,
    color: '#888',
    fontFamily: 'monospace',
    wordBreak: 'break-all' as const,
  },
  refreshBtn: {
    background: 'transparent',
    border: '1px solid #333',
    borderRadius: 3,
    color: '#888',
    fontSize: 10,
    padding: '2px 6px',
    cursor: 'pointer',
  },
  episodeList: {
    maxHeight: 180,
    overflowY: 'auto' as const,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 2,
    background: '#1a1a1a',
    borderRadius: 4,
    border: '1px solid #2a2a2a',
    padding: '4px',
  },
  checkRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '4px 6px',
    borderRadius: 3,
    cursor: 'pointer',
    fontSize: 12,
  },
  checkbox: {
    flexShrink: 0,
    accentColor: '#3a6ea5',
  },
  epLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    minWidth: 0,
    overflow: 'hidden',
  },
  epIndex: {
    color: '#888',
    fontSize: 11,
    fontFamily: 'monospace',
    flexShrink: 0,
  },
  gradeTag: {
    fontSize: 10,
    fontWeight: 600,
    flexShrink: 0,
  },
  epTask: {
    color: '#aaa',
    fontSize: 11,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  textInput: {
    background: '#2a2a2a',
    border: '1px solid #444',
    borderRadius: 4,
    color: '#e0e0e0',
    padding: '6px 8px',
    fontSize: 12,
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box' as const,
  },
  actionBtn: {
    background: '#3a6ea5',
    border: 'none',
    borderRadius: 4,
    color: '#fff',
    padding: '7px 14px',
    fontSize: 12,
    cursor: 'pointer',
    alignSelf: 'flex-start' as const,
  },
  statusBox: {
    background: '#1a1a1a',
    border: '1px solid #333',
    borderRadius: 4,
    padding: '8px 10px',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
    fontSize: 12,
  },
  resultPath: {
    fontSize: 11,
    color: '#888',
    wordBreak: 'break-all' as const,
  },
  errorText: {
    fontSize: 12,
    color: '#e05252',
  },
  spinner: {
    display: 'inline-block',
    animation: 'spin 1s linear infinite',
    fontSize: 14,
  },
  empty: {
    color: '#555',
    fontSize: 12,
    padding: '6px 0',
  },
  emptyState: {
    fontSize: 13,
    color: 'var(--color-text-dim)',
    padding: '24px',
    textAlign: 'center' as const,
  },
}
