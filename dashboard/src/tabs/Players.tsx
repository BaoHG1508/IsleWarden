import { useState } from 'react'
import { useApp } from '../App'
import { api, query } from '../api'
import type { PlayerSummary, RiskBand } from '../types'
import { Badges, Band, BAND_LABELS, Card, DataTable, Field, Loading, useLoad, when } from '../ui'

const WINDOWS = [7, 14, 30, 90]

export function Players() {
  const { config, go, refreshToken, onUnauthorized } = useApp()
  const [windowDays, setWindowDays] = useState(config.risk.windowDays)
  const [band, setBand] = useState<RiskBand | ''>('')
  const [search, setSearch] = useState('')

  const state = useLoad(
    () => api<PlayerSummary[]>('/players' + query({ window: windowDays, limit: 300 })),
    [windowDays, refreshToken],
    onUnauthorized,
  )

  // Filter client-side: a community server's player list is small enough not to need another request.
  const needle = search.trim().toLowerCase()
  const rows = (state.data ?? []).filter(
    (p) => (!band || p.band === band)
      && (!needle || p.steamId.includes(needle) || !!p.discordName?.toLowerCase().includes(needle)),
  )

  return (
    <Card title="Người chơi">
      <div className="row" style={{ marginBottom: 12 }}>
        <Field label="Cửa sổ thời gian">
          <select value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))}>
            {WINDOWS.map((d) => <option key={d} value={d}>{d} ngày</option>)}
          </select>
        </Field>
        <Field label="Lọc mức rủi ro">
          <select value={band} onChange={(e) => setBand(e.target.value as RiskBand | '')}>
            <option value="">tất cả</option>
            {Object.entries(BAND_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </Field>
        <Field label="Tìm Steam ID / Discord">
          <input type="text" value={search} placeholder="7656119… hoặc tên Discord" onChange={(e) => setSearch(e.target.value)} />
        </Field>
      </div>

      <Loading state={state}>
        <DataTable
          columns={['Steam ID', 'Discord', 'Rủi ro', 'Vì sao', 'Phiên', 'Thiết bị', 'Lần cuối']}
          rows={rows}
          empty="Không có người chơi nào khớp bộ lọc."
          onRowClick={(p) => go('players', p.steamId)}
          render={(p) => (
            <>
              <td className="mono">{p.steamId}<Badges {...p} /></td>
              <td>{p.discordName ?? <span className="muted">—</span>}</td>
              <td><Band value={p.band} score={p.score} /></td>
              <td className="muted">{p.reasons.join(' · ') || '—'}</td>
              <td>{p.sessions}</td>
              <td>{p.devices}</td>
              <td className="nowrap muted">{when(p.lastSeenUtc)}</td>
            </>
          )}
        />
      </Loading>
    </Card>
  )
}
