import { useState } from 'react'
import { useApp } from '../App'
import { api, post } from '../api'
import type { DeviceRecord } from '../types'
import { Card, DataTable, Loading, useLoad, useToast, when } from '../ui'

export function Devices() {
  const { go, refreshToken, onUnauthorized } = useApp()
  const toast = useToast()
  const [busy, setBusy] = useState(false)

  const state = useLoad(() => api<DeviceRecord[]>('/devices'), [refreshToken], onUnauthorized)
  const devices = state.data ?? []
  const pending = devices.filter((d) => d.status === 'pending')

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

  const columns = ['Thiết bị', 'Steam ID', 'Tên máy', 'Trạng thái', 'Thông báo', 'Đăng ký', '']
  const renderRow = (d: DeviceRecord) => (
    <>
      <td className="mono">{d.deviceId.slice(0, 12)}…</td>
      <td className="mono">{d.steamId}</td>
      <td>{d.machineName}</td>
      <td>
        {d.status}
        {d.reviewReason && <div className="muted" style={{ fontSize: 12 }}>cần xem: {d.reviewReason}</div>}
      </td>
      <td className="mono muted">{d.consentVersion}</td>
      <td className="nowrap muted">{when(d.createdUtc)}</td>
      <td className="right">
        {d.status !== 'approved' && (
          <button className="act" disabled={busy}
            onClick={() => run('Đã duyệt.', () => post(`/devices/${d.deviceId}/approve`))}>
            Duyệt
          </button>
        )}{' '}
        {d.status !== 'rejected' && (
          <button className="act danger" disabled={busy}
            onClick={() => run('Đã từ chối.', () => post(`/devices/${d.deviceId}/reject`))}>
            Từ chối
          </button>
        )}
      </td>
    </>
  )

  return (
    <>
      <Loading state={state}>
        <Card
          title={`Chờ duyệt (${pending.length})`}
          hint="Máy có cờ rủi ro (trùng linh kiện với tài khoản khác hoặc tài khoản đang bị ban, không có fingerprint) luôn chờ duyệt, kể cả khi bật tự duyệt."
        >
          <DataTable columns={columns} rows={pending} render={renderRow}
            empty="Không có thiết bị nào đang chờ."
            onRowClick={(d) => go('players', d.steamId)} />
        </Card>

        <Card title={`Tất cả thiết bị (${devices.length})`}>
          <DataTable columns={columns} rows={devices} render={renderRow}
            onRowClick={(d) => go('players', d.steamId)} />
        </Card>
      </Loading>
    </>
  )
}
