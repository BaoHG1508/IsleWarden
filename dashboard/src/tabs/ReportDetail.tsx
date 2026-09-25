import { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'
import type { ReportDetail as ReportDetailData } from '../types'
import { Card, Chip, DataTable, Loading, Sev, stamp, useLoad, useToast } from '../ui'

export function ReportDetail({ id }: { id: number }) {
  const { go, refreshToken, onUnauthorized } = useApp()
  const toast = useToast()
  const [processes, setProcesses] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)

  const state = useLoad(
    () => api<ReportDetailData>(`/reports/${id}`),
    [id, refreshToken],
    onUnauthorized,
  )

  const showProcesses = async () => {
    setBusy(true)
    try {
      const full = await api<ReportDetailData>(`/reports/${id}?processes=true`)
      setProcesses(full.processes ?? [])
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button className="act" style={{ marginBottom: 12 }} onClick={() => go('reports')}>
        ← Danh sách báo cáo
      </button>

      <Loading state={state}>
        {state.data && (
          <Card>
            <h2>Báo cáo #{state.data.summary.id}</h2>
            <div className="row muted" style={{ fontSize: 12.5, marginBottom: 12 }}>
              <span>{stamp(state.data.summary.receivedUtc)}</span>
              <span className="mono">{state.data.summary.steamId}</span>
              <span>phiên <span className="mono">{state.data.summary.sessionId.slice(0, 10)}…</span></span>
              <button className="act" onClick={() => go('players', state.data!.summary.steamId)}>
                Mở hồ sơ người chơi
              </button>
            </div>

            <DataTable
              columns={['Mã', 'Mức', 'Thông điệp', 'Chi tiết']}
              rows={state.data.findings}
              empty="Báo cáo sạch — không có phát hiện nào."
              render={(f) => (
                <>
                  <td><Chip>{f.code}</Chip></td>
                  <td><Sev value={f.severity} /></td>
                  <td>{f.message}</td>
                  <td className="mono muted">{f.detail ?? '—'}</td>
                </>
              )}
            />

            <h3>Phần mềm đang chạy lúc quét</h3>
            <p className="hint">
              Chỉ là <b>tên</b> tiến trình, đúng phạm vi đã công bố với người chơi.
              Mỗi lần xem đều được ghi vào nhật ký admin.
            </p>
            {processes === null ? (
              <button className="act" disabled={busy} onClick={showProcesses}>
                {busy ? 'Đang tải…' : 'Xem danh sách'}
              </button>
            ) : processes.length === 0 ? (
              <div className="empty">Báo cáo này không kèm danh sách phần mềm (policy không bật).</div>
            ) : (
              <div className="mono muted processes">
                {processes.map((p) => <div key={p}>{p}</div>)}
              </div>
            )}
          </Card>
        )}
      </Loading>
    </>
  )
}
