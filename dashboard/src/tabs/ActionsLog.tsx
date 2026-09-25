import { useApp } from '../App'
import { api } from '../api'
import type { AdminAction } from '../types'
import { Card, Chip, DataTable, Loading, stamp, useLoad } from '../ui'

export function ActionsLog() {
  const { go, refreshToken, onUnauthorized } = useApp()
  const state = useLoad(() => api<AdminAction[]>('/actions?limit=200'), [refreshToken], onUnauthorized)

  return (
    <Card
      title="Nhật ký thao tác"
      hint="Mọi quyết định và mọi lần xem danh sách phần mềm đều nằm ở đây — để trả lời được câu “tại sao tôi bị ban”."
    >
      <Loading state={state}>
        <DataTable
          columns={['Thời điểm', 'Thao tác', 'Đối tượng', 'Ghi chú', 'Báo cáo']}
          rows={state.data ?? []}
          empty="Chưa có thao tác nào."
          render={(a) => (
            <>
              <td className="nowrap muted">{stamp(a.createdUtc)}</td>
              <td><Chip>{a.action}</Chip></td>
              <td className="mono">
                {a.subjectType === 'steam_id' ? (
                  <button className="act" onClick={() => go('players', a.subjectValue)}>
                    {a.subjectValue}
                  </button>
                ) : a.subjectValue}
              </td>
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
      </Loading>
    </Card>
  )
}
