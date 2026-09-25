import { useState } from 'react'
import { useApp } from '../App'
import { api, query } from '../api'
import { SEVERITIES, type ReportSummary } from '../types'
import { Card, Chip, DataTable, Field, Loading, Sev, severityOfRank, stamp, useLoad } from '../ui'

interface Filters {
  steamId: string
  code: string
  minRank: string
  onlyDirty: boolean
  limit: number
}

const EMPTY: Filters = { steamId: '', code: '', minRank: '', onlyDirty: false, limit: 100 }

export function Reports() {
  const { config, go, refreshToken, onUnauthorized } = useApp()
  const [draft, setDraft] = useState<Filters>(EMPTY)
  const [applied, setApplied] = useState<Filters>(EMPTY)

  const state = useLoad(
    () => api<ReportSummary[]>('/reports' + query({
      steamId: applied.steamId.trim(),
      code: applied.code,
      minRank: applied.minRank,
      onlyDirty: applied.onlyDirty || undefined,
      limit: applied.limit,
    })),
    [applied, refreshToken],
    onUnauthorized,
  )

  const set = <K extends keyof Filters>(name: K, value: Filters[K]) =>
    setDraft((f) => ({ ...f, [name]: value }))

  return (
    <Card title="Báo cáo quét">
      <div className="row" style={{ marginBottom: 12 }}>
        <Field label="Steam ID">
          <input type="text" placeholder="tất cả" value={draft.steamId}
            onChange={(e) => set('steamId', e.target.value)} />
        </Field>
        <Field label="Mã phát hiện">
          <select value={draft.code} onChange={(e) => set('code', e.target.value)}>
            <option value="">tất cả</option>
            {config.codes.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
        <Field label="Mức tối thiểu">
          <select value={draft.minRank} onChange={(e) => set('minRank', e.target.value)}>
            <option value="">tất cả</option>
            {SEVERITIES.map((s, i) => <option key={s} value={i}>{s}</option>)}
          </select>
        </Field>
        <Field label="Số dòng">
          <input type="number" min={10} max={500} style={{ width: 90 }} value={draft.limit}
            onChange={(e) => set('limit', Number(e.target.value))} />
        </Field>
        <label className="check" style={{ marginTop: 14 }}>
          <input type="checkbox" checked={draft.onlyDirty} onChange={(e) => set('onlyDirty', e.target.checked)} />
          chỉ báo cáo có phát hiện
        </label>
        <button className="act" style={{ marginTop: 12 }} onClick={() => setApplied(draft)}>Lọc</button>
      </div>

      <Loading state={state}>
        <DataTable
          columns={['#', 'Thời điểm', 'Steam ID', 'Kết quả', 'Phát hiện', 'Nặng nhất']}
          rows={state.data ?? []}
          empty="Không có báo cáo nào khớp bộ lọc."
          onRowClick={(r) => go('reports', String(r.id))}
          render={(r) => (
            <>
              <td className="mono muted">{r.id}</td>
              <td className="nowrap muted">{stamp(r.receivedUtc)}</td>
              <td className="mono">{r.steamId}</td>
              <td>
                {r.clean
                  ? <span className="band clean">sạch</span>
                  : <span className="band medium">có phát hiện</span>}
              </td>
              <td>{r.findingCount}{r.topCode && <> · <Chip>{r.topCode}</Chip></>}</td>
              <td>{r.findingCount > 0 ? <Sev value={severityOfRank(r.worstRank)} /> : '—'}</td>
            </>
          )}
        />
      </Loading>
    </Card>
  )
}
