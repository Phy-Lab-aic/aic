import { useEffect, useState, useRef } from 'react'
import client from '../api/client'

interface RerunViewerProps {
  episodeIndex: number | null
}

export function RerunViewer({ episodeIndex }: RerunViewerProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const prevIndexRef = useRef<number | null>(null)

  useEffect(() => {
    if (episodeIndex === null || episodeIndex === prevIndexRef.current) return
    prevIndexRef.current = episodeIndex

    setLoading(true)
    setError(null)

    client.post(`/rerun/visualize/${episodeIndex}`)
      .then(() => {
        setLoading(false)
      })
      .catch(err => {
        setError(err instanceof Error ? err.message : 'Visualization failed')
        setLoading(false)
      })
  }, [episodeIndex])

  return (
    <div style={styles.container}>
      <div style={styles.toolbar}>
        <span style={styles.title}>Rerun Viewer</span>
        {episodeIndex !== null && (
          <span style={styles.epLabel}>Episode #{episodeIndex}</span>
        )}
        {loading && <span style={styles.loading}>Loading visualization...</span>}
        {error && <span style={styles.error}>{error}</span>}
      </div>
      <iframe
        style={styles.iframe}
        src={import.meta.env.VITE_RERUN_URL ?? "http://localhost:9090"}
        title="Rerun Viewer"
        sandbox="allow-scripts allow-same-origin"
        allowFullScreen
      />
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
    overflow: 'hidden',
    background: '#111',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '8px 12px',
    background: '#1e1e1e',
    borderBottom: '1px solid #333',
    flexShrink: 0,
  },
  title: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#888',
  },
  epLabel: {
    fontSize: '12px',
    color: '#90caf9',
    fontFamily: 'monospace',
  },
  loading: {
    fontSize: '12px',
    color: '#ffc107',
  },
  error: {
    fontSize: '12px',
    color: '#e05252',
  },
  iframe: {
    flex: 1,
    border: 'none',
    width: '100%',
  },
}
