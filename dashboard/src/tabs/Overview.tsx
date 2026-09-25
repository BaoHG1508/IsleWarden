import { useApp } from '../App'
import { api } from '../api'
import type { Overview as OverviewData, PlayerSummary, ReportSummary } from '../types'
import { Badges, Band, bytes, Card, Chip, DataTable, Loading, Sev, severityOfRank, Stat, useLoad, when } from '../ui'

export function Overview() {
  const { go, refreshToken, onUnauthorized, config } = useApp()

  const state = useLoad(
    async () => {
      const [overview, players, reports] = await Promise.all([
        api<OverviewData>('/overview'),
        api<PlayerSummary[]>(`/players?window=${config.risk.windowDays}&limit=8`),
        api<ReportSummary[]>('/reports?onlyDirty=true&limit=8'),
      ])
      return { overview, players, reports }
    },
    [refreshToken],
    onUnauthorized,
  )

  return (
    <Loading state={state}>
      {state.data && (() => {
        const { overview, players, reports } = state.data
        const f = overview.findingsLast24h
        const serious = (f.medium ?? 0) + (f.high ?? 0) + (f.critical ?? 0)
        const risky = players.filter((p) => p.score > 0)

        return (
          <>
            <div className="grid" style={{ marginBottom: 16 }}>
              <Stat value={overview.activeSessions} label="phiên đang chơi" />
              <Stat value={overview.playersLast24h} label="người chơi 24h qua" />
              <Stat value={serious} label="phát hiện đáng chú ý 24h" alert={serious > 0} />
              <Stat value={overview.highRiskPlayers} label="người chơi rủi ro cao" alert={overview.highRiskPlayers > 0} />
              <Stat value={overview.pendingDevices} label="thiết bị chờ duyệt" alert={overview.pendingDevices > 0} />
              <Stat value={overview.activeBans} label="ban còn hiệu lực" />
              <Stat value={overview.whitelisted} label="đang trong whitelist" />
              <Stat
                value={bytes(overview.databaseBytes)}
                label={`${overview.reportCount.toLocaleString('vi-VN')} báo cáo đã lưu`}
              />
            </div>

            <Card title="Cần xem xét trước">
              <DataTable
                columns={['Steam ID', 'Rủi ro', 'Vì sao', 'Lần cuối', '']}
                rows={risky}
                empty="Không có ai đáng chú ý trong cửa sổ đang xem."
                onRowClick={(p) => go('players', p.steamId)}
                render={(p) => (
                  <>
                    <td className="mono">{p.steamId}<Badges {...p} /></td>
                    <td><Band value={p.band} score={p.score} /></td>
                    <td className="muted">{p.reasons.join(' · ') || '—'}</td>
                    <td className="nowrap muted">{when(p.lastSeenUtc)}</td>
                    <td className="right"><button className="act">Hồ sơ</button></td>
                  </>
                )}
              />
            </Card>

            <Card title="Báo cáo có phát hiện, mới nhất">
              <DataTable
                columns={['Thời điểm', 'Steam ID', 'Phát hiện', 'Nặng nhất']}
                rows={reports}
                onRowClick={(r) => go('reports', String(r.id))}
                render={(r) => (
                  <>
                    <td className="nowrap muted">{when(r.receivedUtc)}</td>
                    <td className="mono">{r.steamId}</td>
                    <td>{r.findingCount} — {r.topCode && <Chip>{r.topCode}</Chip>}</td>
                    <td><Sev value={severityOfRank(r.worstRank)} /></td>
                  </>
                )}
              />
            </Card>
          </>
        )
      })()}
    </Loading>
  )
}
