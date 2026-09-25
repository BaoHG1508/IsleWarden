import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, forgetKey, readKey, storeKey } from './api'
import { Login } from './Login'
import type { ServerConfig } from './types'
import { ToastProvider } from './ui'
import { ActionsLog } from './tabs/ActionsLog'
import { Bans } from './tabs/Bans'
import { Devices } from './tabs/Devices'
import { Maintenance } from './tabs/Maintenance'
import { Overview } from './tabs/Overview'
import { PlayerProfile } from './tabs/PlayerProfile'
import { Players } from './tabs/Players'
import { ReportDetail } from './tabs/ReportDetail'
import { Reports } from './tabs/Reports'

const TABS = [
  ['overview', 'Tổng quan'],
  ['players', 'Người chơi'],
  ['reports', 'Báo cáo quét'],
  ['devices', 'Thiết bị'],
  ['bans', 'Ban list'],
  ['actions', 'Nhật ký admin'],
  ['maint', 'Bảo trì'],
] as const

export type TabId = (typeof TABS)[number][0]

export interface Route {
  tab: TabId
  id?: string
}

interface AppState {
  config: ServerConfig
  route: Route
  go: (tab: TabId, id?: string) => void
  /** Bumped by `refresh()` and each auto-refresh tick; tabs list it in their load deps to reload. */
  refreshToken: number
  refresh: () => void
  onUnauthorized: () => void
}

const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const state = useContext(AppContext)
  if (!state) throw new Error('useApp phải nằm trong AppContext.')
  return state
}

/** Hash routing, so admins can share direct links to a player profile or report. */
function parseHash(): Route {
  const [tab, id] = window.location.hash.replace(/^#\/?/, '').split('/')
  const known = TABS.some(([t]) => t === tab)
  return { tab: known ? (tab as TabId) : 'overview', id: id || undefined }
}

export function App() {
  const [key, setKey] = useState<string | null>(readKey)
  const [config, setConfig] = useState<ServerConfig | null>(null)
  const [route, setRoute] = useState<Route>(parseHash)
  const [refreshToken, setRefreshToken] = useState(0)
  const [auto, setAuto] = useState(false)

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  // Sign back in with a key left in sessionStorage; on failure, drop it and show the login screen.
  useEffect(() => {
    if (!key) {
      setConfig(null)
      return
    }
    let alive = true
    api<ServerConfig>('/config', {}, key)
      .then((result) => alive && setConfig(result))
      .catch(() => {
        if (!alive) return
        forgetKey()
        setKey(null)
      })
    return () => {
      alive = false
    }
  }, [key])

  useEffect(() => {
    if (!auto) return
    const timer = setInterval(() => setRefreshToken((t) => t + 1), 15000)
    return () => clearInterval(timer)
  }, [auto])

  const go = useCallback((tab: TabId, id?: string) => {
    window.location.hash = '#/' + tab + (id ? '/' + encodeURIComponent(id) : '')
  }, [])

  const signOut = useCallback(() => {
    forgetKey()
    setKey(null)
  }, [])

  if (!key || !config) {
    return (
      <Login
        onSignedIn={(value) => {
          storeKey(value)
          setKey(value)
        }}
      />
    )
  }

  const state: AppState = {
    config,
    route,
    go,
    refreshToken,
    refresh: () => setRefreshToken((t) => t + 1),
    onUnauthorized: signOut,
  }

  return (
    <AppContext.Provider value={state}>
      <ToastProvider>
        <div className="topbar">
          <header>
            <h1>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 1.6 20.6 4.9v6.3c0 5.6-3.6 9.9-8.6 11.3-5-1.4-8.6-5.7-8.6-11.3V4.9Z"
                  fill="none" stroke="#39b3c6" strokeWidth="1.6" strokeLinejoin="round" />
                <path d="M8.6 10.6 10.9 12.9 15.6 8.2"
                  fill="none" stroke="#e7eef5" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Chống gian lận
            </h1>
            <span className="tag">
              chế độ {config.mode} · thông báo {config.disclosureVersion} · chặn từ {config.enforceThreshold}
            </span>
            <div className="spacer" />
            <label className="check">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              tự làm mới 15s
            </label>
            <button className="act" onClick={state.refresh}>Làm mới</button>
            <button className="act" onClick={signOut}>Thoát</button>
          </header>
          <nav>
            {TABS.map(([id, label]) => (
              <button
                key={id}
                className={route.tab === id ? 'on' : undefined}
                onClick={() => go(id)}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
        <main>
          <Screen />
        </main>
      </ToastProvider>
    </AppContext.Provider>
  )
}

function Screen() {
  const { route } = useApp()

  switch (route.tab) {
    case 'players':
      return route.id ? <PlayerProfile steamId={route.id} /> : <Players />
    case 'reports':
      return route.id ? <ReportDetail id={Number(route.id)} /> : <Reports />
    case 'devices':
      return <Devices />
    case 'bans':
      return <Bans />
    case 'actions':
      return <ActionsLog />
    case 'maint':
      return <Maintenance />
    default:
      return <Overview />
  }
}
