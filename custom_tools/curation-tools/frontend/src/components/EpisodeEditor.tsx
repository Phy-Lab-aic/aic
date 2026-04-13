import { useState, useEffect } from 'react'
import { GRADE_COLORS } from '../types'
import type { Episode } from '../types'

interface EpisodeEditorProps {
  episode: Episode | null
  onSave: (index: number, grade: string | null, tags: string[]) => Promise<void>
}

export function EpisodeEditor({ episode, onSave }: EpisodeEditorProps) {
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (episode) {
      setTags(episode.tags)
      setTagInput('')
      setSaveError(null)
    }
  }, [episode])

  const handleAddTag = () => {
    const trimmed = tagInput.trim()
    if (trimmed && !tags.includes(trimmed)) {
      const newTags = [...tags, trimmed]
      setTags(newTags)
      setTagInput('')
      // Auto-save tags
      if (episode) {
        void saveTags(newTags)
      }
    } else {
      setTagInput('')
    }
  }

  const handleRemoveTag = (tag: string) => {
    const newTags = tags.filter(t => t !== tag)
    setTags(newTags)
    // Auto-save tags
    if (episode) {
      void saveTags(newTags)
    }
  }

  const saveTags = async (newTags: string[]) => {
    if (!episode) return
    setSaving(true)
    setSaveError(null)
    try {
      await onSave(episode.episode_index, episode.grade, newTags)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleTagKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleAddTag()
    }
  }

  if (!episode) {
    return (
      <div style={styles.container}>
        <div style={styles.title}>Episode Details</div>
        <div style={styles.empty}>Select an episode to edit</div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      {/* Episode header */}
      <div style={styles.headerRow}>
        <div>
          <div style={styles.epNumber}>Episode #{episode.episode_index}</div>
          <div style={styles.meta}>
            {episode.length} frames
            {episode.grade && (
              <span style={{
                ...styles.gradeBadge,
                background: GRADE_COLORS[episode.grade],
              }}>
                {episode.grade}
              </span>
            )}
          </div>
        </div>
        {saving && <span style={styles.savingIndicator}>saving...</span>}
      </div>

      {saveError && <div style={styles.error}>{saveError}</div>}

      {/* Tags */}
      <div style={styles.section}>
        <label style={styles.label}>Tags</label>
        <div style={styles.tagInputRow}>
          <input
            style={styles.input}
            type="text"
            placeholder="Add tag + Enter"
            value={tagInput}
            onChange={e => setTagInput(e.target.value)}
            onKeyDown={handleTagKeyDown}
          />
        </div>
        <div style={styles.tagChips}>
          {tags.map(tag => (
            <span key={tag} style={styles.chip}>
              {tag}
              <button
                style={styles.chipRemove}
                onClick={() => handleRemoveTag(tag)}
              >
                x
              </button>
            </span>
          ))}
          {tags.length === 0 && <span style={styles.noTags}>No tags yet</span>}
        </div>
      </div>

      {/* Preset tags */}
      <div style={styles.section}>
        <label style={styles.label}>Quick Tags</label>
        <div style={styles.presetRow}>
          {['good-demo', 'bad-grasp', 'collision', 'slow', 'incomplete', 'review'].map(preset => (
            <button
              key={preset}
              style={{
                ...styles.presetBtn,
                ...(tags.includes(preset) ? styles.presetActive : {}),
              }}
              onClick={() => {
                if (tags.includes(preset)) {
                  handleRemoveTag(preset)
                } else {
                  const newTags = [...tags, preset]
                  setTags(newTags)
                  if (episode) void saveTags(newTags)
                }
              }}
            >
              {preset}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '14px',
    borderBottom: '1px solid #222',
  },
  headerRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: '14px',
  },
  epNumber: {
    fontSize: '14px',
    fontWeight: 600,
    color: '#d0d8e0',
    marginBottom: '3px',
  },
  meta: {
    fontSize: '11px',
    color: '#666',
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  gradeBadge: {
    fontSize: '10px',
    fontWeight: 700,
    color: '#fff',
    padding: '0 5px',
    borderRadius: '3px',
    lineHeight: '16px',
  },
  savingIndicator: {
    fontSize: '10px',
    color: '#ffc107',
    fontStyle: 'italic',
  },
  title: {
    fontSize: '10px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#666',
    marginBottom: '8px',
  },
  empty: {
    color: '#555',
    fontSize: '12px',
    padding: '8px 0',
  },
  section: {
    marginBottom: '12px',
  },
  label: {
    display: 'block',
    fontSize: '10px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: '#555',
    marginBottom: '5px',
  },
  tagInputRow: {
    display: 'flex',
    gap: '6px',
    marginBottom: '6px',
  },
  input: {
    flex: 1,
    background: '#1a1a1a',
    border: '1px solid #2a2a2a',
    borderRadius: '4px',
    color: '#e0e0e0',
    padding: '5px 8px',
    fontSize: '12px',
    outline: 'none',
  },
  tagChips: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '4px',
    minHeight: '20px',
  },
  chip: {
    background: '#1a2530',
    border: '1px solid #2a4a6a',
    borderRadius: '12px',
    color: '#7ab8e0',
    fontSize: '11px',
    padding: '1px 8px',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  chipRemove: {
    background: 'none',
    border: 'none',
    color: '#556',
    cursor: 'pointer',
    fontSize: '10px',
    padding: '0',
    lineHeight: 1,
  },
  noTags: {
    color: '#3a3a3a',
    fontSize: '11px',
  },
  error: {
    color: '#e05252',
    fontSize: '11px',
    marginBottom: '8px',
    padding: '4px 8px',
    background: '#2a1414',
    borderRadius: '4px',
  },
  presetRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '4px',
  },
  presetBtn: {
    background: '#1a1a1a',
    border: '1px solid #2a2a2a',
    borderRadius: '12px',
    color: '#555',
    fontSize: '10px',
    padding: '2px 8px',
    cursor: 'pointer',
    transition: 'all 0.1s',
  },
  presetActive: {
    background: '#1a2530',
    borderColor: '#2a4a6a',
    color: '#7ab8e0',
  },
}
