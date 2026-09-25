import { useState } from 'react'
import { useApp } from '../App'
import { api, del, post } from '../api'
import type { BanRecord } from '../types'
import { Card, Chip, DataTable, Field, Loading, stamp, useLoad, useToast } from '../ui'

const SUBJECTS = [
  { value: 'steam_id', label: 'Steam ID' },
  { value: 'device', label: 'Thiết bị' },
  { value: 'component', label: 'Linh kiện (hash)' },
] as const

export function Bans() {
  const { refreshToken, onUnauthorized } = useApp()
  const toast = useToast()
  const [subjectType, setSubjectType] = useState<string>('steam_id')
  const [subjectValue, setSubjectValue] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const state = useLoad(() => api<BanRecord[]>('/bans'), [refreshToken], onUnauthorized)

  const run = async (label: string, action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      toast(label)
      state.reload()
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), true)
    } finally {
      setBusy(false)
    }
  }

  const bans = state.data ?? []

  return (
    <>
      <Card title="Thêm ban thủ công">
        <div className="row">
          <Field label="Loại">
            <select value={subjectType} onChange={(e) => setSubjectType(e.target.value)}>
              {SUBJECTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="Giá trị" grow>
            <input type="text" value={subjectValue} onChange={(e) => setSubjectValue(e.target.value)} />
          </Field>
          <Field label="Lý do" grow>
            <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <button
            className="act danger"
            style={{ marginTop: 14 }}
            disabled={busy || !subjectValue.trim()}
            onClick={() => run('Đã thêm.', async () => {
              await post('/bans', {
                subjectType,
                subjectValue: subjectValue.trim(),
                reason: reason.trim() || null,
              })
              setSubjectValue('')
              setReason('')
            })}
          >
            Thêm
          </button>
        </div>
      </Card>

      <Loading state={state}>
        <Card title={`Ban list (${bans.length})`}>
          <DataTable
            columns={['Loại', 'Giá trị', 'Lý do', 'Tạo lúc', 'Hết hạn', '']}
            rows={bans}
            empty="Chưa có ban nào."
            render={(b) => (
              <>
                <td><Chip>{b.subjectType}</Chip></td>
                <td className="mono">
                  {b.subjectValue.length > 28 ? b.subjectValue.slice(0, 28) + '…' : b.subjectValue}
                </td>
                <td>{b.reason ?? '—'}</td>
                <td className="nowrap muted">{stamp(b.createdUtc)}</td>
                <td className="nowrap muted">
                  {b.expiresUtc
                    ? (new Date(b.expiresUtc) < new Date() ? 'đã hết' : stamp(b.expiresUtc))
                    : 'vĩnh viễn'}
                </td>
                <td className="right">
                  <button className="act" disabled={busy}
                    onClick={() => run('Đã gỡ.', () => del(`/bans/${b.id}`))}>
                    Gỡ
                  </button>
                </td>
              </>
            )}
          />
        </Card>
      </Loading>
    </>
  )
}
