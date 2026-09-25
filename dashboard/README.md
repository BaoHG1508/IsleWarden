# Admin dashboard (React + Vite)

The admin UI for the server in `server/`. It builds straight into `server/islewarden_server/static/admin`,
so the server serves it at `http://<server>/admin/` without a copy step.

## Development

```bash
npm install
npm run dev
```

`npm run dev` starts Vite on its own port and **proxies `/api` to `http://localhost:5088`**. Run the
server alongside it (`.venv\Scripts\python -m islewarden_server --dev` in `server/`), and you can edit the
UI with hot reload against the real API. If the server uses another port, change `server.proxy` in
`vite.config.ts`.

## Build

```bash
npm run build
```

`build-release.ps1` in the repository root runs this step before it packages the server. Pass
`-SkipAdminUi` to skip it on a machine without Node.

## Structure

| Path | Contents |
|---|---|
| `src/types.ts` | TypeScript copy of the JSON the server returns. **When you change a server record in `server/islewarden_server/` (`records.py`, `dashboard.py`), change it here too.** |
| `src/api.ts` | `fetch` wrapper that adds the `X-Admin-Key` header; a 401 throws `UnauthorizedError` |
| `src/App.tsx` | Layout, hash routing (`#/players/<steamId>`), auto-refresh |
| `src/ui.tsx` | Shared pieces: tables, stat cards, severity chips, toasts, the `useLoad` hook |
| `src/tabs/` | One file per tab |

The admin key lives in `sessionStorage`, so it's gone when the tab closes. It's sent with every
request in a header and never appears in a URL.

UI text is Vietnamese; code and comments are English.
