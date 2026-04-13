import { useState } from 'react'
import { GRADE_COLORS } from '../types'
import type { Episode } from '../types'

type Filter = 'all' | 'ungraded' | 'graded'

interface EpisodeListProps {
  episodes: Episode[]
  loading: boolean
  error: string | null
  onEpisodeSelect: (episode: Episode) => void
  selectedIndex: number | null
}

export function EpisodeList({ episodes, loading, error, onEpisodeSelect, selectedIndex }: EpisodeListProps) {
  const [filter, setFilter] = useState<Filter>('all')

  const handleClick = (episode: Episode) => {
    onEpisodeSelect(episode)
  }

  const filtered = episodes.filter(ep => {
    if (filter === 'ungraded') return !ep.grade
    if (filter === 'graded') return !!ep.grade
    return true
  })

  if (loading && episodes.length === 0) {
    return <div style={styles.message}>Loading episodes...</div>
  }

  if (error) {
    return <div style={styles.errorMessage}>{error}</div>
  }

  if (episodes.length === 0) {
    return <div style={styles.message}>No dataset loaded</div>
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.headerTitle}>Episodes</span>
        <span style={styles.count}>{filtered.length}</span>
      </div>

      {/* Filter tabs */}
      <div style={styles.filterRow}>
        {(['all', 'ungraded', 'graded'] as const).map(f => (
          <button
            key={f}
            style={{
              ...styles.filterBtn,
              ...(filter === f ? styles.filterActive : {}),
            }}
            onClick={() => setFilter(f)}
          >
            {f === 'all' ? 'All' : f === 'ungraded' ? 'Todo' : 'Done'}
          </button>
        ))}
      </div>

      <div style={styles.list} role="listbox">
        {filtered.map(ep => {
          const isSelected = selectedIndex === ep.episode_index
          return (
            <div
              key={ep.episode_index}
              role="option"
              tabIndex={0}
              aria-selected={isSelected}
              style={{
                ...styles.item,
                background: isSelected ? '#1a2a3a' : 'transparent',
                borderLeft: isSelected ? '3px solid #3a6ea5' : '3px solid transparent',
              }}
              onClick={() => handleClick(ep)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  handleClick(ep)
                }
              }}
            >
              <div style={styles.itemTop}>
                <span style={styles.index}>#{ep.episode_index}</span>
                <div style={styles.badges}>
                  {ep.grade ? (
                    <span style={{
                      ...styles.grade,
                      background: GRADE_COLORS[ep.grade] ?? '#666',
                    }}>
                      {ep.grade}
                    </span>
                  ) : (
                    <span style={styles.ungraded}>--</span>
                  )}
                </div>
              </div>
              <div style={styles.itemBottom}>
                <span style={styles.length}>{ep.length}f</span>
                {ep.tags.length > 0 && (
                  <span style={styles.tagCount}>{ep.tags.length} tags</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '8px 12px',
    borderBottom: '1px solid #222',
  },
  headerTitle: {
    fontSize: '10px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#666',
  },
  count: {
    fontSize: '10px',
    color: '#555',
    background: '#1e1e1e',
    padding: '1px 6px',
    borderRadius: '10px',
    fontFamily: 'monospace',
  },
  filterRow: {
    display: 'flex',
    gap: '2px',
    padding: '6px 8px',
    borderBottom: '1px solid #222',
  },
  filterBtn: {
    flex: 1,
    background: 'transparent',
    border: '1px solid #2a2a2a',
    borderRadius: '4px',
    color: '#666',
    fontSize: '10px',
    fontWeight: 600,
    padding: '3px 0',
    cursor: 'pointer',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  filterActive: {
    background: '#1a2a3a',
    borderColor: '#3a6ea5',
    color: '#90caf9',
  },
  list: {
    overflowY: 'auto',
    flex: 1,
  },
  item: {
    padding: '6px 10px',
    cursor: 'pointer',
    borderBottom: '1px solid #1a1a1a',
    transition: 'background 0.1s',
  },
  itemTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '2px',
  },
  index: {
    fontFamily: 'monospace',
    fontSize: '12px',
    color: '#aab8c8',
  },
  badges: {
    display: 'flex',
    gap: '4px',
    alignItems: 'center',
  },
  grade: {
    fontSize: '10px',
    fontWeight: 700,
    color: '#fff',
    padding: '0px 5px',
    borderRadius: '3px',
    lineHeight: '16px',
  },
  ungraded: {
    fontSize: '10px',
    color: '#3a3a3a',
    fontFamily: 'monospace',
  },
  itemBottom: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '10px',
    color: '#444',
  },
  length: {
    color: '#555',
    fontFamily: 'monospace',
  },
  tagCount: {
    color: '#4a7a9a',
  },
  message: {
    padding: '16px 12px',
    color: '#555',
    fontSize: '12px',
  },
  errorMessage: {
    padding: '16px 12px',
    color: '#e05252',
    fontSize: '12px',
  },
}
