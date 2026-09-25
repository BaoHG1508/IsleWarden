import { useState } from 'react'
import { api } from './api'
import type { ServerConfig } from './types'

export function Login({ onSignedIn }: { onSignedIn: (key: string) => void }) {
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setError('')
    setBusy(true)
    try {
      // Verify the key with a real request before storing it.
      await api<ServerConfig>('/config', {}, key.trim())
      onSignedIn(key.trim())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="gate">
      <div className="card">
        <h2>Bảng điều khiển chống gian lận</h2>
        <p>
          Nhập khoá quản trị (<span className="mono">IsleWarden:AdminKey</span>). Khoá chỉ nằm trong
          tab này và mất khi bạn đóng tab.
        </p>
        <div className="row">
          <input
            type="password"
            value={key}
            autoComplete="off"
            placeholder="Khoá quản trị"
            style={{ flex: 1 }}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
          <button className="act primary" disabled={busy || !key.trim()} onClick={submit}>
            {busy ? 'Đang kiểm tra…' : 'Vào'}
          </button>
        </div>
        {error && <p className="err">{error}</p>}
        <p className="muted" style={{ fontSize: 12 }}>
          Chỉ mở trang này qua HTTPS — khoá quản trị đi kèm mọi yêu cầu.
        </p>
      </div>
    </div>
  )
}
