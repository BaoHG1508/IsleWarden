import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react'
import { UnauthorizedError } from './api'
import { SEVERITIES, type RiskBand, type Severity } from './types'

// ---------- Formatting ----------

export function when(iso: string | null | undefined): string {
  if (!iso) return '—'
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'vừa xong'
  if (minutes < 60) return `${minutes} phút trước`
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} giờ trước`
  if (minutes < 60 * 24 * 7) return `${Math.round(minutes / 1440)} ngày trước`
  return new Date(iso).toLocaleDateString('vi-VN')
}

export const stamp = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('vi-VN') : '—'

export const bytes = (n: number) =>
  n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`

export const severityOfRank = (rank: number): Severity => SEVERITIES[rank] ?? 'info'

export const BAND_LABELS: Record<RiskBand, string> = {
  clean: 'sạch',
  low: 'thấp',
  medium: 'trung bình',
  high: 'cao',
}

/** Labels for the codes a lease can end with (AccessCodes in Core/Protocol/Access.cs). */
export const END_LABELS: Record<string, string> = {
  'lease-expired': 'mất tín hiệu',
  'lease-revoked': 'admin thu hồi',
  'lease-released': 'launcher trả',
  'lease-invalid': 'không hợp lệ',
  'anticheat-blocked': 'anti-cheat',
  banned: 'bị ban',
  'device-rejected': 'máy bị từ chối',
  'discord-not-linked': 'chưa liên kết Discord',
  'discord-not-member': 'rời Discord server',
  'discord-role-missing': 'mất role Discord',
}

// ---------- Building blocks ----------

export const Chip = ({ children }: { children: ReactNode }) => <span className="chip">{children}</span>

export const Sev = ({ value }: { value: Severity }) => <span className={`sev ${value}`}>{value}</span>

export const Band = ({ value, score }: { value: RiskBand; score: number }) => (
  <span className={`band ${value}`}>{BAND_LABELS[value]} · {score}</span>
)

export function Badges({ banned, watched, whitelisted, bypassed }: {
  banned?: boolean; watched?: boolean; whitelisted?: boolean; bypassed?: boolean
}) {
  return (
    <>
      {banned && <span className="tag ban">ban</span>}
      {watched && <span className="tag watch">theo dõi</span>}
      {whitelisted && <span className="tag wl">whitelist</span>}
      {bypassed && <span className="tag bypass">miễn trừ AC</span>}
    </>
  )
}

export const Card = ({ title, hint, children }: { title?: string; hint?: string; children: ReactNode }) => (
  <div className="card">
    {title && <h2>{title}</h2>}
    {hint && <p className="hint">{hint}</p>}
    {children}
  </div>
)

export const Stat = ({ value, label, alert }: { value: ReactNode; label: string; alert?: boolean }) => (
  <div className={`stat${alert ? ' alert' : ''}`}>
    <div className="v">{value}</div>
    <div className="l">{label}</div>
  </div>
)

export const Field = ({ label, grow, children }: { label: string; grow?: boolean; children: ReactNode }) => (
  <label className={`f${grow ? ' grow' : ''}`}>
    {label}
    {children}
  </label>
)

/** Table with a sticky header; pass onRowClick to make whole rows clickable. */
export function DataTable<T>({ columns, rows, render, onRowClick, empty }: {
  columns: string[]
  rows: T[]
  render: (row: T) => ReactNode
  onRowClick?: (row: T) => void
  empty?: string
}) {
  if (rows.length === 0) return <div className="empty">{empty ?? 'Chưa có dữ liệu.'}</div>

  return (
    <table>
      <thead>
        <tr>{columns.map((c, i) => <th key={i}>{c}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr
            key={i}
            className={onRowClick ? 'click' : undefined}
            onClick={onRowClick && ((event) => {
              // Buttons inside a row do their own thing; don't open the row too.
              if (!(event.target as HTMLElement).closest('button')) onRowClick(row)
            })}
          >
            {render(row)}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ---------- Toasts ----------

type Toast = { id: number; message: string; bad?: boolean }
const ToastContext = createContext<(message: string, bad?: boolean) => void>(() => {})

export const useToast = () => useContext(ToastContext)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const next = useRef(0)

  const push = useCallback((message: string, bad?: boolean) => {
    const id = next.current++
    setToasts((list) => [...list, { id, message, bad }])
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 4200)
  }, [])

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts">
        {toasts.map((t) => <div key={t.id} className={t.bad ? 'bad' : undefined}>{t.message}</div>)}
      </div>
    </ToastContext.Provider>
  )
}

// ---------- Loading ----------

export interface Loaded<T> {
  data: T | undefined
  error: string | null
  loading: boolean
  reload: () => void
}

/**
 * Calls the API and tracks loading state. Reloads when `deps` change or on `reload()`.
 * A rejected key goes to `onUnauthorized` so the App can return to the sign-in screen.
 */
export function useLoad<T>(
  load: () => Promise<T>,
  deps: unknown[],
  onUnauthorized?: () => void,
): Loaded<T> {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const latest = useRef(0)

  useEffect(() => {
    const run = ++latest.current
    setLoading(true)
    load()
      .then((result) => {
        if (run !== latest.current) return // result of an outdated call
        setData(result)
        setError(null)
      })
      .catch((e: unknown) => {
        if (run !== latest.current) return
        if (e instanceof UnauthorizedError) onUnauthorized?.()
        setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (run === latest.current) setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  return useMemo(
    () => ({ data, error, loading, reload: () => setTick((t) => t + 1) }),
    [data, error, loading],
  )
}

export function Loading({ state, children }: { state: Loaded<unknown>; children: ReactNode }) {
  if (state.error) return <div className="card err">{state.error}</div>
  if (state.data === undefined) return <div className="empty">Đang tải…</div>
  return <>{children}</>
}
