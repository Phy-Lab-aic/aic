import { useEffect, useState, useRef } from 'react'
import client from '../api/client'

interface ScalarData {
  episode_index: number
  num_frames: number
  observations: Record<string, number[]>
  actions: Record<string, number[]>
}

interface ScalarChartProps {
  episodeIndex: number | null
  currentFrame: number
}

const COLORS = [
  '#4fc3f7', '#81c784', '#ffb74d', '#e57373', '#ba68c8',
  '#4dd0e1', '#aed581', '#ffd54f', '#ff8a65', '#9575cd',
  '#26c6da', '#dce775', '#ffca28', '#ff7043', '#7e57c2',
]

function MiniChart({ label, series, color, currentFrame, collapsed }: {
  label: string
  series: number[]
  color: string
  currentFrame: number
  collapsed: boolean
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (collapsed) return
    const canvas = canvasRef.current
    if (!canvas || series.length === 0) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const w = canvas.width
    const h = canvas.height
    const min = Math.min(...series)
    const max = Math.max(...series)
    const range = max - min || 1

    ctx.clearRect(0, 0, w, h)

    // Background
    ctx.fillStyle = '#111'
    ctx.fillRect(0, 0, w, h)

    // Grid lines
    ctx.strokeStyle = '#1e1e1e'
    ctx.lineWidth = 1
    for (let i = 0; i < 4; i++) {
      const y = (h / 4) * i
      ctx.beginPath()
      ctx.moveTo(0, y)
      ctx.lineTo(w, y)
      ctx.stroke()
    }

    // Data line
    ctx.strokeStyle = color
    ctx.lineWidth = 1.5
    ctx.beginPath()
    for (let i = 0; i < series.length; i++) {
      const x = (i / (series.length - 1)) * w
      const y = h - ((series[i] - min) / range) * (h - 4) - 2
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()

    // Current frame indicator
    if (currentFrame >= 0 && currentFrame < series.length) {
      const x = (currentFrame / (series.length - 1)) * w
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 1
      ctx.setLineDash([2, 2])
      ctx.beginPath()
      ctx.moveTo(x, 0)
      ctx.lineTo(x, h)
      ctx.stroke()
      ctx.setLineDash([])

      // Value dot
      const y = h - ((series[currentFrame] - min) / range) * (h - 4) - 2
      ctx.fillStyle = color
      ctx.beginPath()
      ctx.arc(x, y, 3, 0, Math.PI * 2)
      ctx.fill()
    }
  }, [series, color, currentFrame, collapsed])

  const currentVal = currentFrame >= 0 && currentFrame < series.length
    ? series[currentFrame].toFixed(3)
    : '--'

  return (
    <div style={chartStyles.chartItem}>
      <div style={chartStyles.chartHeader}>
        <span style={{ ...chartStyles.chartLabel, color }}>{label}</span>
        <span style={chartStyles.chartValue}>{currentVal}</span>
      </div>
      {!collapsed && (
        <canvas
          ref={canvasRef}
          width={400}
          height={40}
          style={chartStyles.canvas}
        />
      )}
    </div>
  )
}

export function ScalarChart({ episodeIndex, currentFrame }: ScalarChartProps) {
  const [data, setData] = useState<ScalarData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [obsCollapsed, setObsCollapsed] = useState(false)
  const [actCollapsed, setActCollapsed] = useState(false)

  useEffect(() => {
    if (episodeIndex === null) {
      setData(null)
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    client.get<ScalarData>(`/scalars/${episodeIndex}`)
      .then(res => setData(res.data))
      .catch(err => { setData(null); setError(err?.message || 'Failed to load scalar data') })
      .finally(() => setLoading(false))
  }, [episodeIndex])

  if (episodeIndex === null) return null

  if (loading) {
    return (
      <div style={chartStyles.container}>
        <div style={chartStyles.loading}>Loading scalar data...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div style={chartStyles.container}>
        <div style={chartStyles.error}>Scalar data unavailable</div>
      </div>
    )
  }

  if (!data) return null

  const obsKeys = Object.keys(data.observations)
  const actKeys = Object.keys(data.actions)

  if (obsKeys.length === 0 && actKeys.length === 0) return null

  return (
    <div style={chartStyles.container}>
      {obsKeys.length > 0 && (
        <div style={chartStyles.section}>
          <div
            role="button"
            tabIndex={0}
            style={chartStyles.sectionHeader}
            onClick={() => setObsCollapsed(!obsCollapsed)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                setObsCollapsed(!obsCollapsed)
              }
            }}
          >
            <span style={chartStyles.sectionTitle}>
              {obsCollapsed ? '\u25B6' : '\u25BC'} Observations
            </span>
            <span style={chartStyles.sectionCount}>{obsKeys.length}</span>
          </div>
          {obsKeys.map((key, i) => (
            <MiniChart
              key={key}
              label={key.replace('observation.', '').replace('state.', '')}
              series={data.observations[key]}
              color={COLORS[i % COLORS.length]}
              currentFrame={currentFrame}
              collapsed={obsCollapsed}
            />
          ))}
        </div>
      )}

      {actKeys.length > 0 && (
        <div style={chartStyles.section}>
          <div
            role="button"
            tabIndex={0}
            style={chartStyles.sectionHeader}
            onClick={() => setActCollapsed(!actCollapsed)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                setActCollapsed(!actCollapsed)
              }
            }}
          >
            <span style={chartStyles.sectionTitle}>
              {actCollapsed ? '\u25B6' : '\u25BC'} Actions
            </span>
            <span style={chartStyles.sectionCount}>{actKeys.length}</span>
          </div>
          {actKeys.map((key, i) => (
            <MiniChart
              key={key}
              label={key.replace('action.', '')}
              series={data.actions[key]}
              color={COLORS[(i + 5) % COLORS.length]}
              currentFrame={currentFrame}
              collapsed={actCollapsed}
            />
          ))}
        </div>
      )}
    </div>
  )
}

const chartStyles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    overflow: 'visible',
    flexShrink: 0,
  },
  loading: {
    padding: '12px',
    fontSize: '11px',
    color: '#555',
  },
  error: {
    padding: '12px',
    fontSize: '11px',
    color: '#e57373',
  },
  section: {
    borderBottom: '1px solid #222',
  },
  sectionHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 12px',
    cursor: 'pointer',
    background: '#161616',
    borderBottom: '1px solid #1e1e1e',
  },
  sectionTitle: {
    fontSize: '10px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: '#666',
  },
  sectionCount: {
    fontSize: '10px',
    color: '#444',
    fontFamily: 'monospace',
  },
  chartItem: {
    padding: '3px 12px',
    borderBottom: '1px solid #1a1a1a',
  },
  chartHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '2px',
  },
  chartLabel: {
    fontSize: '10px',
    fontFamily: 'monospace',
    fontWeight: 500,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: '180px',
  },
  chartValue: {
    fontSize: '10px',
    fontFamily: 'monospace',
    color: '#888',
  },
  canvas: {
    width: '100%',
    height: '40px',
    borderRadius: '2px',
  },
}
