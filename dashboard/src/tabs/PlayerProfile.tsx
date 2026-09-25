import { useState } from 'react'
import { useApp } from '../App'
import { api, del, post, query } from '../api'
import type { BanScope, DiscordRoleState, PlayerDetail } from '../types'
import { Band, Card, Chip, DataTable, END_LABELS, Field, Loading, Sev, stamp, useLoad, useToast, when } from '../ui'

const SCOPES: { value: BanScope; label: string }[] = [
  { value: 'steam', label: 'chỉ Steam ID' },
  { value: 'device', label: 'Steam ID + thiết bị' },
  { value: 'all', label: '+ cả linh kiện (chống lách bằng máy khác)' },
]

const ROLE_STATE_LABELS: Record<DiscordRoleState, string> = {
  ok: 'có role được vào chơi',
  notMember: 'không còn trong Discord server',
  roleMissing: 'chưa có hoặc đã mất role',
}

/** A date input's value as the end of that day in UTC, or null when empty. */
const endOfDay = (date: string) => (date ? new Date(date + 'T23:59:59Z').toISOString() : null)

export function PlayerProfile({ steamId }: { steamId: string }) {
  const { config, go, refreshToken, onUnauthorized } = useApp()
  const toast = useToast()

  const [scope, setScope] = useState<BanScope>('device')
  const [until, setUntil] = useState('')
  const [reason, setReason] = useState('')
  const [bypassReason, setBypassReason] = useState('')
  const [bypassUntil, setBypassUntil] = useState('')
  const [busy, setBusy] = useState(false)

  const state = useLoad(
    () => api<PlayerDetail>(`/players/${encodeURIComponent(steamId)}` + query({ window: config.risk.windowDays })),
    [steamId, refreshToken],
    onUnauthorized,
  )

  /** Runs a write, then reloads the profile; failures are shown, never swallowed. */
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

  return (
    <>
      <button className="act" style={{ marginBottom: 12 }} onClick={() => go('players')}>
        ← Danh sách người chơi
      </button>

      <Loading state={state}>
        {state.data && (() => {
          const player = state.data
          const active = player.sessions.filter((s) => s.state === 'active')
          const worst = player.software[0]
          const bypass = player.bypass
          const bypassActive = !!bypass && (!bypass.expiresUtc || new Date(bypass.expiresUtc) > new Date())

          return (
            <>
              <Card>
                <h2>Hồ sơ · <span className="mono">{player.steamId}</span></h2>
                <div className="row" style={{ marginBottom: 10 }}>
                  <Band value={player.risk.band} score={player.risk.score} />
                  {player.banned && <span className="tag ban">đang bị ban</span>}
                  {player.watched && <span className="tag watch">đang theo dõi</span>}
                  {player.whitelisted && <span className="tag wl">trong whitelist</span>}
                  {bypassActive && <span className="tag bypass">miễn trừ anti-cheat</span>}
                </div>
                <div className="muted" style={{ fontSize: 12.5 }}>
                  {player.risk.reasons.length > 0
                    ? player.risk.reasons.map((r, i) => <div key={i}>{r}</div>)
                    : 'Không có phát hiện nào trong cửa sổ đang xem.'}
                </div>

                <h3>Quyết định</h3>
                <div className="row">
                  <Field label="Phạm vi ban">
                    <select value={scope} onChange={(e) => setScope(e.target.value as BanScope)}>
                      {SCOPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select>
                  </Field>
                  <Field label="Hết hạn (trống = vĩnh viễn)">
                    <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
                  </Field>
                  <Field label="Lý do (người chơi sẽ thấy)" grow>
                    <input
                      type="text"
                      value={reason}
                      placeholder="Ví dụ: chạy Cheat Engine trong lúc chơi"
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </Field>
                </div>
                <div className="row" style={{ marginTop: 10 }}>
                  <button
                    className="act danger"
                    disabled={busy}
                    onClick={() => run('Đã ban.', () =>
                      post(`/players/${encodeURIComponent(steamId)}/ban`, {
                        reason: reason.trim() || null,
                        expiresUtc: endOfDay(until),
                        scope,
                        evidence: worst ? `${worst.code}: ${worst.message}` : 'không kèm báo cáo',
                      }))}
                  >
                    Ban
                  </button>
                  <button
                    className="act"
                    disabled={busy || !player.banned}
                    onClick={() => run('Đã gỡ ban.', () =>
                      post(`/players/${encodeURIComponent(steamId)}/unban`, { note: reason.trim() || null }))}
                  >
                    Gỡ ban
                  </button>
                  <button
                    className="act"
                    disabled={busy}
                    onClick={() => run(player.watched ? 'Đã bỏ theo dõi.' : 'Đã đánh dấu theo dõi.', () =>
                      post(`/players/${encodeURIComponent(steamId)}/watch`, {
                        watch: !player.watched,
                        note: reason.trim() || null,
                      }))}
                  >
                    {player.watched ? 'Bỏ theo dõi' : 'Đánh dấu theo dõi'}
                  </button>
                  <button
                    className="act"
                    disabled={busy}
                    onClick={() => {
                      const note = window.prompt('Ghi chú về người chơi này:')
                      if (note?.trim()) {
                        run('Đã lưu ghi chú.', () =>
                          post(`/players/${encodeURIComponent(steamId)}/note`, { note: note.trim() }))
                      }
                    }}
                  >
                    Thêm ghi chú
                  </button>
                  {active.length > 0 && (
                    <button
                      className="act danger"
                      disabled={busy}
                      onClick={() => run('Đã thu hồi phiên.', () =>
                        Promise.all(active.map((s) =>
                          post(`/sessions/${encodeURIComponent(s.sessionId)}/revoke`, {
                            note: 'admin thu hồi từ bảng điều khiển',
                          }))))}
                    >
                      Thu hồi phiên đang chơi
                    </button>
                  )}
                </div>
                <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
                  Ban lấy phát hiện nặng nhất trong cửa sổ làm bằng chứng và ghi vào nhật ký admin.
                </p>
              </Card>

              <Card
                title="Discord"
                hint="Người chơi đăng nhập launcher bằng Steam + Discord. Gỡ liên kết để họ có thể liên kết tài khoản khác ở lần đăng nhập sau; suất chơi đang giữ sẽ kết thúc ở heartbeat kế tiếp."
              >
                {player.discord ? (
                  <div className="row">
                    <span>
                      <b>{player.discord.discordName}</b>{' '}
                      <span className="mono muted">({player.discord.discordId})</span>{' '}
                      <span className={`tag ${player.discord.roleState === 'ok' ? 'wl' : 'ban'}`}>
                        {ROLE_STATE_LABELS[player.discord.roleState]}
                      </span>{' '}
                      <span className="muted">
                        · kiểm tra {when(player.discord.checkedUtc)} · liên kết {when(player.discord.linkedUtc)}
                      </span>
                    </span>
                    <div className="spacer" />
                    <button
                      className="act danger"
                      disabled={busy}
                      onClick={() => {
                        if (window.confirm('Gỡ liên kết Discord của người chơi này?')) {
                          run('Đã gỡ liên kết Discord.', () => del(`/players/${encodeURIComponent(steamId)}/discord`))
                        }
                      }}
                    >
                      Gỡ liên kết
                    </button>
                  </div>
                ) : (
                  <p className="muted" style={{ margin: 0 }}>
                    {config.discordRequired
                      ? 'Chưa liên kết Discord — người chơi cần chạy lệnh login trong launcher.'
                      : 'Server không bắt buộc Discord (đăng nhập chỉ bằng Steam).'}
                  </p>
                )}
              </Card>

              <Card
                title="Miễn trừ anti-cheat"
                hint="Cho streamer/staff chạy OBS hay công cụ bị gắn cờ mà không bị chặn. Chỉ bỏ qua cổng anti-cheat và bước duyệt máy — vẫn chặn ban, vẫn phải đồng ý thông báo, báo cáo quét vẫn được ghi."
              >
                {!config.allowBypass && (
                  <p className="err" style={{ marginTop: 0 }}>
                    Server đang tắt mọi miễn trừ (AllowAntiCheatBypass = false) — bản ghi dưới đây hiện không có tác dụng.
                  </p>
                )}
                {bypass ? (
                  <p style={{ marginTop: 0 }}>
                    <span className={`tag ${bypassActive ? 'bypass' : 'ban'}`} style={{ marginLeft: 0 }}>
                      {bypassActive ? 'đang miễn trừ' : 'đã hết hạn'}
                    </span>{' '}
                    {bypass.reason} · cấp {when(bypass.createdUtc)} ·{' '}
                    {bypass.expiresUtc ? `hết hạn ${stamp(bypass.expiresUtc)}` : 'tới khi gỡ'}
                  </p>
                ) : (
                  <p className="muted" style={{ marginTop: 0 }}>Người chơi này không được miễn trừ.</p>
                )}
                <div className="row">
                  <Field label="Lý do (bắt buộc)" grow>
                    <input
                      type="text"
                      value={bypassReason}
                      placeholder="Ví dụ: streamer, chạy OBS + overlay"
                      onChange={(e) => setBypassReason(e.target.value)}
                    />
                  </Field>
                  <Field label="Hết hạn (trống = tới khi gỡ)">
                    <input type="date" value={bypassUntil} onChange={(e) => setBypassUntil(e.target.value)} />
                  </Field>
                  <button
                    className="act primary"
                    style={{ marginTop: 14 }}
                    disabled={busy || !bypassReason.trim()}
                    onClick={() => run(bypass ? 'Đã cập nhật miễn trừ.' : 'Đã cấp miễn trừ.', () =>
                      post(`/players/${encodeURIComponent(steamId)}/bypass`, {
                        reason: bypassReason.trim(),
                        expiresUtc: endOfDay(bypassUntil),
                      }))}
                  >
                    {bypass ? 'Cập nhật' : 'Cấp miễn trừ'}
                  </button>
                  {bypass && (
                    <button
                      className="act danger"
                      style={{ marginTop: 14 }}
                      disabled={busy}
                      onClick={() => run('Đã gỡ miễn trừ.', () =>
                        del(`/players/${encodeURIComponent(steamId)}/bypass`))}
                    >
                      Gỡ miễn trừ
                    </button>
                  )}
                </div>
              </Card>

              <Card
                title="Phần mềm bị gắn cờ"
                hint="Gộp theo nội dung: một công cụ chạy suốt phiên chỉ hiện một dòng, cột “lần” cho biết số báo cáo đã ghi nhận."
              >
                <DataTable
                  columns={['Mã', 'Mức', 'Phát hiện', 'Chi tiết', 'Lần', 'Gần nhất']}
                  rows={player.software}
                  empty="Không có phần mềm nào bị gắn cờ trong cửa sổ đang xem."
                  render={(s) => (
                    <>
                      <td><Chip>{s.code}</Chip></td>
                      <td><Sev value={s.severity} /></td>
                      <td>{s.message}</td>
                      <td className="mono muted">{s.detail ?? '—'}</td>
                      <td>{s.hits}</td>
                      <td className="nowrap muted">{when(s.lastUtc)}</td>
                    </>
                  )}
                />
              </Card>

              <Card title="Thiết bị">
                <DataTable
                  columns={['Thiết bị', 'Tên máy', 'Trạng thái', 'Thông báo đã đồng ý', 'Đăng ký', '']}
                  rows={player.devices}
                  render={(d) => (
                    <>
                      <td className="mono">{d.deviceId.slice(0, 12)}…</td>
                      <td>{d.machineName}</td>
                      <td>
                        {d.status}
                        {d.reviewReason && <div className="muted" style={{ fontSize: 12 }}>cần xem: {d.reviewReason}</div>}
                      </td>
                      <td className="mono muted">{d.consentVersion}</td>
                      <td className="nowrap muted">{when(d.createdUtc)}</td>
                      <td className="right">
                        {d.status === 'pending' && (
                          <>
                            <button
                              className="act"
                              disabled={busy}
                              onClick={() => run('Đã duyệt thiết bị.', () => post(`/devices/${d.deviceId}/approve`))}
                            >
                              Duyệt
                            </button>{' '}
                            <button
                              className="act danger"
                              disabled={busy}
                              onClick={() => run('Đã từ chối thiết bị.', () => post(`/devices/${d.deviceId}/reject`))}
                            >
                              Từ chối
                            </button>
                          </>
                        )}
                      </td>
                    </>
                  )}
                />

                <h2 style={{ marginTop: 20 }}>Phiên gần đây</h2>
                <DataTable
                  columns={['Bắt đầu', 'Trạng thái', 'Heartbeat cuối', 'Kết thúc vì', 'Phiên']}
                  rows={player.sessions}
                  render={(s) => (
                    <>
                      <td className="nowrap muted">{stamp(s.startedUtc)}</td>
                      <td>{s.state}</td>
                      <td className="nowrap muted">{when(s.lastHeartbeatUtc)}</td>
                      <td>
                        {s.endCode ? (
                          <>
                            <Chip>{END_LABELS[s.endCode] ?? s.endCode}</Chip>
                            {s.endReason && <span className="muted"> {s.endReason}</span>}
                          </>
                        ) : '—'}
                      </td>
                      <td className="mono muted">{s.sessionId.slice(0, 10)}…</td>
                    </>
                  )}
                />

                <h2 style={{ marginTop: 20 }}>Nhật ký thao tác với người chơi này</h2>
                <DataTable
                  columns={['Thời điểm', 'Thao tác', 'Ghi chú', 'Báo cáo']}
                  rows={player.actions}
                  empty="Chưa có thao tác nào."
                  render={(a) => (
                    <>
                      <td className="nowrap muted">{stamp(a.createdUtc)}</td>
                      <td><Chip>{a.action}</Chip></td>
                      <td className="muted">{a.note ?? '—'}</td>
                      <td className="mono muted">
                        {a.reportId ? (
                          <button className="act" onClick={() => go('reports', String(a.reportId))}>
                            #{a.reportId}
                          </button>
                        ) : '—'}
                      </td>
                    </>
                  )}
                />
              </Card>
            </>
          )
        })()}
      </Loading>
    </>
  )
}
