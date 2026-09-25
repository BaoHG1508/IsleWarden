import { useState } from 'react'
import { useApp } from '../App'
import { api, post } from '../api'
import type { Overview } from '../types'
import { bytes, Card, DataTable, Field, Loading, Stat, useLoad, useToast, when } from '../ui'

export function Maintenance() {
  const { config, refreshToken, onUnauthorized } = useApp()
  const toast = useToast()
  const [days, setDays] = useState(30)
  const [busy, setBusy] = useState(false)

  const state = useLoad(() => api<Overview>('/overview'), [refreshToken], onUnauthorized)

  const prune = async () => {
    if (!window.confirm(`Xoá toàn bộ báo cáo cũ hơn ${days} ngày? Không khôi phục được.`)) return
    setBusy(true)
    try {
      const result = await post<{ deleted: number }>('/maintenance/prune', { days })
      toast(`Đã xoá ${result.deleted} báo cáo.`)
      state.reload()
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), true)
    } finally {
      setBusy(false)
    }
  }

  const settings: [string, string][] = [
    ['Chế độ', config.mode],
    ['Phiên bản thông báo', config.disclosureVersion],
    ['Ngưỡng chặn tự động', config.enforceThreshold],
    ['Chu kỳ heartbeat', `${config.heartbeatSeconds} giây`],
    ['Ân hạn suất chơi (mất tín hiệu)', `${config.leaseGraceSeconds} giây`],
    ['Tự duyệt thiết bị mới', config.autoApproveDevices ? 'có (trừ máy có cờ rủi ro)' : 'không'],
    ['Bắt buộc Discord', config.discordRequired ? `có — server ${config.discordGuildId ?? '(chưa đặt)'}` : 'không (chỉ Steam)'],
    ['Role được vào chơi', config.discordRoleIds.length > 0 ? config.discordRoleIds.join(', ') : 'mọi thành viên'],
    ['Kiểm tra lại role', `mỗi ${config.discordRecheckMinutes} phút`],
    ['Miễn trừ anti-cheat', config.allowBypass ? 'đang bật' : 'đang tắt toàn server'],
    ['Đồng bộ whitelist', config.whitelistMode],
    ['Kick khi hết suất chơi (RCON 0x30)', config.kickOnRevoke ? 'bật — chưa kiểm chứng' : 'tắt'],
    ['Cửa sổ chấm rủi ro', `${config.risk.windowDays} ngày, bán rã ${config.risk.halfLifeDays} ngày`],
  ]

  return (
    <>
      <Card title="Dung lượng và hạn lưu trữ">
        <Loading state={state}>
          {state.data && (
            <div className="grid">
              <Stat value={bytes(state.data.databaseBytes)} label="kích thước database" />
              <Stat value={state.data.reportCount.toLocaleString('vi-VN')} label="báo cáo đang lưu" />
              <Stat value={when(state.data.oldestReportUtc)} label="báo cáo cũ nhất" />
            </div>
          )}
        </Loading>

        <h3>Dọn báo cáo cũ</h3>
        <p className="hint">
          Launcher gửi báo cáo mỗi {config.heartbeatSeconds} giây nên bảng này phình rất nhanh.
          Bằng chứng đã gắn vào ban vẫn được giữ lại dạng tóm tắt sau khi báo cáo gốc bị xoá.
        </p>
        <div className="row">
          <Field label="Xoá báo cáo cũ hơn">
            <input type="number" min={1} style={{ width: 100 }} value={days}
              onChange={(e) => setDays(Number(e.target.value))} />
          </Field>
          <span className="muted" style={{ marginTop: 16 }}>ngày</span>
          <button className="act danger" style={{ marginTop: 14 }} disabled={busy || days < 1} onClick={prune}>
            Dọn
          </button>
        </div>
      </Card>

      <Card title="Cấu hình đang chạy">
        <DataTable
          columns={['Mục', 'Giá trị']}
          rows={settings}
          render={([name, value]) => (
            <>
              <td>{name}</td>
              <td className="mono">{value}</td>
            </>
          )}
        />
        <p className="hint" style={{ margin: '10px 0 0' }}>
          Sửa các giá trị này trong <span className="mono">appsettings.json</span> /{' '}
          <span className="mono">server-policy.json</span> rồi khởi động lại server.
        </p>
      </Card>
    </>
  )
}
