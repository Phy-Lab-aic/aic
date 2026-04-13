import { useState, useEffect } from 'react'
import { useDataset } from '../hooks/useDataset'
import client from '../api/client'
import type { DatasetInfo } from '../types'

interface DatasetEntry {
  name: string
  path: string
}

interface DatasetLoaderProps {
  onDatasetLoaded: (dataset: DatasetInfo) => void
}

export function DatasetLoader({ onDatasetLoaded }: DatasetLoaderProps) {
  const [availableDatasets, setAvailableDatasets] = useState<DatasetEntry[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)
  const [manualPath, setManualPath] = useState('')
  const { dataset, loading, error, loadDataset } = useDataset()

  // Fetch available datasets on mount
  useEffect(() => {
    const fetchList = async () => {
      try {
        const resp = await client.get<DatasetEntry[]>('/datasets/list')
        setAvailableDatasets(resp.data)
      } catch {
        setListError('Failed to fetch dataset list')
      } finally {
        setListLoading(false)
      }
    }
    void fetchList()
  }, [])

  // Notify parent when dataset changes
  useEffect(() => {
    if (dataset) {
      onDatasetLoaded(dataset)
    }
  }, [dataset, onDatasetLoaded])

  const [deleting, setDeleting] = useState<string | null>(null)

  const handleSelect = async (entry: DatasetEntry) => {
    await loadDataset(entry.path)
  }

  const handleDelete = async (entry: DatasetEntry, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`Delete dataset "${entry.name}" from HF Hub? This cannot be undone.`)) return
    const repoId = `Phy-lab/${entry.name}`
    setDeleting(entry.name)
    try {
      await client.delete(`/hf-sync/repos/${repoId}`)
      setAvailableDatasets(prev => prev.filter(d => d.name !== entry.name))
    } catch {
      setListError(`Failed to delete ${entry.name}`)
    } finally {
      setDeleting(null)
    }
  }

  const handleManualLoad = async () => {
    if (!manualPath.trim()) return
    await loadDataset(manualPath.trim())
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleManualLoad()
  }

  return (
    <div style={styles.container}>
      <div style={styles.title}>Datasets</div>

      <div style={styles.inputRow}>
        <input
          style={styles.input}
          type="text"
          placeholder="Dataset path or HF repo..."
          value={manualPath}
          onChange={e => setManualPath(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <button
          style={{ ...styles.button, opacity: loading ? 0.6 : 1 }}
          onClick={handleManualLoad}
          disabled={loading}
        >
          {loading ? '...' : 'Load'}
        </button>
      </div>

      {listLoading && <div style={styles.message}>Scanning datasets...</div>}
      {listError && <div style={styles.error}>{listError}</div>}

      {!listLoading && availableDatasets.length === 0 && (
        <div style={styles.message}>No datasets found</div>
      )}

      <div style={styles.list}>
        {availableDatasets.map(entry => {
          const isSelected = dataset?.path === entry.path
          return (
            <div
              key={entry.path}
              style={{
                ...styles.item,
                background: isSelected ? '#2a3a4a' : 'transparent',
                borderLeft: isSelected ? '2px solid #3a6ea5' : '2px solid transparent',
                opacity: loading ? 0.6 : 1,
                pointerEvents: loading ? 'none' : 'auto',
              }}
              onClick={() => handleSelect(entry)}
            >
              <div style={styles.itemHeader}>
                <div style={styles.itemName}>{entry.name}</div>
                <button
                  style={styles.deleteButton}
                  onClick={(e) => handleDelete(entry, e)}
                  disabled={deleting === entry.name}
                  title="Delete from HF Hub"
                >
                  {deleting === entry.name ? '...' : '×'}
                </button>
              </div>
              <div style={styles.itemPath}>{entry.path}</div>
            </div>
          )
        })}
      </div>

      {loading && <div style={styles.message}>Loading...</div>}
      {error && <div style={styles.error}>{error}</div>}

      {dataset && (
        <div style={styles.info}>
          <div style={styles.infoRow}>
            <span style={styles.label}>Episodes</span>
            <span style={styles.value}>{dataset.total_episodes}</span>
          </div>
          <div style={styles.infoRow}>
            <span style={styles.label}>Tasks</span>
            <span style={styles.value}>{dataset.total_tasks}</span>
          </div>
          <div style={styles.infoRow}>
            <span style={styles.label}>FPS</span>
            <span style={styles.value}>{dataset.fps}</span>
          </div>
          {dataset.robot_type && (
            <div style={styles.infoRow}>
              <span style={styles.label}>Robot</span>
              <span style={styles.value}>{dataset.robot_type}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '12px',
    borderBottom: '1px solid #333',
  },
  title: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#888',
    marginBottom: '8px',
  },
  inputRow: {
    display: 'flex',
    gap: '6px',
    marginBottom: '8px',
  },
  input: {
    flex: 1,
    background: '#2a2a2a',
    border: '1px solid #444',
    borderRadius: '4px',
    color: '#e0e0e0',
    padding: '6px 8px',
    fontSize: '13px',
    outline: 'none',
  },
  button: {
    background: '#3a6ea5',
    border: 'none',
    borderRadius: '4px',
    color: '#fff',
    padding: '6px 12px',
    fontSize: '13px',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: '2px',
  },
  item: {
    padding: '8px 10px',
    cursor: 'pointer',
    borderRadius: '4px',
    transition: 'background 0.1s',
  },
  itemHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  itemName: {
    fontSize: '13px',
    color: '#c0d8f0',
    fontWeight: 500,
  },
  deleteButton: {
    background: 'transparent',
    border: 'none',
    color: '#666',
    fontSize: '16px',
    cursor: 'pointer',
    padding: '0 4px',
    lineHeight: 1,
    borderRadius: '2px',
  },
  itemPath: {
    fontSize: '10px',
    color: '#666',
    fontFamily: 'monospace',
    marginTop: '2px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  message: {
    padding: '8px 0',
    color: '#666',
    fontSize: '12px',
  },
  error: {
    marginTop: '6px',
    color: '#e05252',
    fontSize: '12px',
  },
  info: {
    marginTop: '8px',
    background: '#222',
    borderRadius: '4px',
    padding: '8px',
  },
  infoRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '12px',
    marginBottom: '3px',
  },
  label: {
    color: '#888',
  },
  value: {
    color: '#c8e6c9',
    fontFamily: 'monospace',
  },
}
