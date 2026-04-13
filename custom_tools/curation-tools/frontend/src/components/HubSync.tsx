import { useState, useEffect, useCallback } from 'react'
import client from '../api/client'

interface MountDetail {
  repo_id: string
  mount_point: string
  mounted_at: string
}

interface HubSyncStatus {
  org: string
  mounted_repos: string[]
  mount_details: MountDetail[]
  last_scan: string | null
  errors: string[]
  initialized: boolean
}

interface ScanResult {
  scanned: number
  new_mounts: string[]
  already_mounted: string[]
  failed: Record<string, string>
}

function timeAgo(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime()
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function HubSync() {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<HubSyncStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanResult | null>(null)
  const [scanError, setScanError] = useState<string | null>(null)
  const [unmounting, setUnmounting] = useState<Set<string>>(new Set())
  const [errorsOpen, setErrorsOpen] = useState(false)
  const [showPasswordDialog, setShowPasswordDialog] = useState(false)
  const [sudoPassword, setSudoPassword] = useState('')
  const [_needsPassword, setNeedsPassword] = useState(false)

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await client.get<HubSyncStatus>('/hf-sync/status')
      setStatus(resp.data)
      setStatusError(null)
    } catch {
      setStatusError('Failed to fetch HF sync status')
    }
  }, [])

  useEffect(() => {
    if (!open) return
    void fetchStatus()
  }, [open, fetchStatus])

  const doScan = async (password?: string) => {
    setScanning(true)
    setScanResult(null)
    setScanError(null)
    setNeedsPassword(false)
    try {
      const body = password ? { password } : undefined
      const resp = await client.post<ScanResult>('/hf-sync/scan', body)
      setScanResult(resp.data)
      if (resp.data.failed && (Array.isArray(resp.data.failed) ? resp.data.failed.length > 0 : Object.keys(resp.data.failed).length > 0)) {
        if (!password) {
          setNeedsPassword(true)
          setShowPasswordDialog(true)
        }
      }
      await fetchStatus()
    } catch {
      setScanError('Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const handleScan = () => doScan()

  const handleScanWithPassword = async () => {
    setShowPasswordDialog(false)
    await doScan(sudoPassword)
    setSudoPassword('')
  }

  const handleUnmount = async (repoId: string) => {
    setUnmounting(prev => new Set(prev).add(repoId))
    try {
      await client.post(`/hf-sync/repos/${encodeURIComponent(repoId)}/unmount`)
      await fetchStatus()
    } catch {
      // ignore — status will reflect reality
    } finally {
      setUnmounting(prev => {
        const next = new Set(prev)
        next.delete(repoId)
        return next
      })
    }
  }

  return (
    <div style={s.container}>
      {/* Header / toggle */}
      <button style={s.header} onClick={() => setOpen(v => !v)} aria-expanded={open} aria-label="HF Hub Sync panel">
        <span style={s.headerTitle}>HF Hub Sync</span>
        <span style={s.headerMeta}>
          {status && (
            <span style={{ color: status.initialized ? '#8bc34a' : 'var(--color-warning)', marginRight: 8, fontSize: 11 }}>
              {status.initialized ? 'active' : 'idle'}
            </span>
          )}
          {status && (
            <span style={{ color: 'var(--color-text-dim)', fontSize: 11, marginRight: 8 }}>
              {status.mounted_repos.length} repos
            </span>
          )}
          <span style={s.chevron}>{open ? '▲' : '▼'}</span>
        </span>
      </button>

      {open && (
        <div style={s.body}>
          {statusError && <div style={s.error}>{statusError}</div>}

          {status && (
            <>
              {/* Stats row */}
              <div style={s.statsRow}>
                <div style={s.stat}>
                  <span style={s.statLabel}>Org</span>
                  <span style={s.statValue}>{status.org || '—'}</span>
                </div>
                <div style={s.stat}>
                  <span style={s.statLabel}>Mounted</span>
                  <span style={s.statValue}>{status.mounted_repos.length}</span>
                </div>
                <div style={s.stat}>
                  <span style={s.statLabel}>Last scan</span>
                  <span style={s.statValue}>
                    {status.last_scan ? timeAgo(status.last_scan) : '—'}
                  </span>
                </div>
              </div>

              {/* Scan button */}
              <button
                style={{ ...s.scanBtn, opacity: scanning ? 0.6 : 1 }}
                onClick={handleScan}
                disabled={scanning}
              >
                {scanning ? (
                  <span style={s.spinner}>⟳</span>
                ) : null}
                {scanning ? 'Scanning...' : 'Scan Now'}
              </button>

              {scanError && <div style={s.error}>{scanError}</div>}

              {scanResult && (
                <div style={s.scanResult}>
                  <span style={{ color: 'var(--color-success)' }}>+{scanResult.new_mounts.length} new</span>
                  {' · '}
                  <span style={{ color: 'var(--color-text-dim)' }}>{scanResult.already_mounted.length} already mounted</span>
                  {Object.keys(scanResult.failed).length > 0 && (
                    <>
                      {' · '}
                      <span style={{ color: 'var(--color-error)' }}>{Object.keys(scanResult.failed).length} failed</span>
                    </>
                  )}
                </div>
              )}

              {/* Sudo password dialog */}
              {showPasswordDialog && (
                <div style={{ background: 'var(--color-bg-raised)', border: '1px solid #555', borderRadius: 6, padding: 12, marginTop: 8 }}>
                  <div style={{ fontSize: 12, color: '#ccc', marginBottom: 8 }}>
                    Mount requires sudo. Enter password:
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input
                      type="password"
                      value={sudoPassword}
                      onChange={e => setSudoPassword(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handleScanWithPassword()}
                      placeholder="sudo password"
                      style={{ flex: 1, padding: '4px 8px', background: 'var(--color-bg)', border: '1px solid var(--color-border)', borderRadius: 4, color: 'var(--color-text)', fontSize: 12 }}
                      autoFocus
                    />
                    <button
                      onClick={handleScanWithPassword}
                      disabled={!sudoPassword || scanning}
                      style={{ padding: '4px 12px', background: 'var(--color-info)', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
                    >
                      Mount
                    </button>
                    <button
                      onClick={() => { setShowPasswordDialog(false); setSudoPassword('') }}
                      style={{ padding: '4px 8px', background: 'transparent', color: 'var(--color-text-dim)', border: '1px solid #555', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {/* Mounted repos table */}
              {status.mount_details.length > 0 && (
                <div style={s.section}>
                  <div style={s.sectionTitle}>Mounted Repos</div>
                  <div style={s.repoList}>
                    {status.mount_details.map(detail => (
                      <div key={detail.repo_id} style={s.repoRow}>
                        <div style={s.repoInfo}>
                          <div style={s.repoName}>{detail.repo_id}</div>
                          <div style={s.repoMeta}>
                            <span style={s.repoMount}>{detail.mount_point}</span>
                            <span style={s.repoDot}>·</span>
                            <span style={s.repoTime}>{timeAgo(detail.mounted_at)}</span>
                          </div>
                        </div>
                        <button
                          style={{
                            ...s.unmountBtn,
                            opacity: unmounting.has(detail.repo_id) ? 0.5 : 1,
                          }}
                          onClick={() => handleUnmount(detail.repo_id)}
                          disabled={unmounting.has(detail.repo_id)}
                          aria-label={`Unmount ${detail.repo_id}`}
                        >
                          {unmounting.has(detail.repo_id) ? '...' : 'Unmount'}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {status.mounted_repos.length === 0 && (
                <div style={s.empty}>
                  No repos mounted yet. Click 'Scan Now' to discover datasets from HuggingFace.
                </div>
              )}

              {/* Errors collapsible */}
              {status.errors.length > 0 && (
                <div style={s.section}>
                  <button style={s.errToggle} onClick={() => setErrorsOpen(v => !v)} aria-expanded={errorsOpen} aria-label="Toggle errors list">
                    <span style={{ color: 'var(--color-error)' }}>
                      {status.errors.length} error{status.errors.length !== 1 ? 's' : ''}
                    </span>
                    <span style={s.chevron}>{errorsOpen ? '▲' : '▼'}</span>
                  </button>
                  {errorsOpen && (
                    <div style={s.errorList}>
                      {status.errors.slice(-10).map((err, i) => (
                        <div key={i} style={s.errorItem}>{err}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {!status && !statusError && (
            <div style={s.loading}>Loading...</div>
          )}
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
  headerMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
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
  statsRow: {
    display: 'flex',
    gap: 12,
  },
  stat: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 2,
  },
  statLabel: {
    fontSize: 10,
    color: '#666',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  statValue: {
    fontSize: 12,
    color: '#c8e6c9',
    fontFamily: 'monospace',
  },
  scanBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    background: '#3a6ea5',
    border: 'none',
    borderRadius: 4,
    color: '#fff',
    padding: '6px 12px',
    fontSize: 12,
    cursor: 'pointer',
    alignSelf: 'flex-start' as const,
  },
  spinner: {
    display: 'inline-block',
    animation: 'spin 1s linear infinite',
    fontSize: 14,
  },
  scanResult: {
    fontSize: 12,
    padding: '4px 8px',
    background: 'var(--color-bg)',
    borderRadius: 4,
    border: '1px solid var(--color-bg-raised)',
  },
  section: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
  },
  sectionTitle: {
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.06em',
    color: '#666',
    marginBottom: 2,
  },
  repoList: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
  },
  repoRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    padding: '6px 8px',
    background: 'var(--color-bg)',
    borderRadius: 4,
    border: '1px solid var(--color-bg-raised)',
  },
  repoInfo: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 2,
    minWidth: 0,
    flex: 1,
  },
  repoName: {
    fontSize: 12,
    color: '#c0d8f0',
    fontWeight: 500,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  repoMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    fontSize: 10,
    color: '#555',
  },
  repoMount: {
    fontFamily: 'monospace',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    maxWidth: 120,
  },
  repoDot: {
    flexShrink: 0,
  },
  repoTime: {
    flexShrink: 0,
  },
  unmountBtn: {
    background: '#3a2020',
    border: '1px solid #5a2020',
    borderRadius: 3,
    color: 'var(--color-error)',
    padding: '3px 8px',
    fontSize: 11,
    cursor: 'pointer',
    flexShrink: 0,
  },
  empty: {
    fontSize: 13,
    color: 'var(--color-text-dim)',
    padding: '24px',
    textAlign: 'center' as const,
  },
  errToggle: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    background: 'transparent',
    border: 'none',
    cursor: 'pointer',
    padding: '4px 0',
    fontSize: 12,
  },
  errorList: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 3,
  },
  errorItem: {
    fontSize: 11,
    color: 'var(--color-error)',
    fontFamily: 'monospace',
    padding: '3px 6px',
    background: '#1e1010',
    borderRadius: 3,
    wordBreak: 'break-all' as const,
  },
  error: {
    fontSize: 12,
    color: 'var(--color-error)',
  },
  loading: {
    fontSize: 12,
    color: 'var(--color-text-dim)',
  },
}
