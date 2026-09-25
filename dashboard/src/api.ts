const STORAGE_KEY = 'iw-admin-key'

/** The admin key is kept in sessionStorage: per tab, gone when the tab closes. */
export const readKey = () => sessionStorage.getItem(STORAGE_KEY)
export const storeKey = (key: string) => sessionStorage.setItem(STORAGE_KEY, key)
export const forgetKey = () => sessionStorage.removeItem(STORAGE_KEY)

/** Wrong or changed admin key; App handles it by returning to the login screen. */
export class UnauthorizedError extends Error {
  constructor() {
    super('Khoá quản trị sai hoặc đã đổi.')
  }
}

export async function api<T>(path: string, init: RequestInit = {}, key = readKey()): Promise<T> {
  const response = await fetch('/api/admin' + path, {
    ...init,
    headers: {
      'X-Admin-Key': key ?? '',
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  })

  if (response.status === 401) throw new UnauthorizedError()

  if (!response.ok) {
    let message = `HTTP ${response.status}`
    try {
      const body = await response.json()
      message = body.error ?? body.detail ?? message
    } catch {
      // Non-JSON error body: keep the HTTP status as the message.
    }
    throw new Error(message)
  }

  return response.status === 204 ? (null as T) : ((await response.json()) as T)
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })

export const del = <T,>(path: string) => api<T>(path, { method: 'DELETE' })

export const query = (params: Record<string, string | number | boolean | null | undefined>) => {
  const search = new URLSearchParams()
  for (const [name, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(name, String(value))
  }
  const text = search.toString()
  return text ? '?' + text : ''
}
