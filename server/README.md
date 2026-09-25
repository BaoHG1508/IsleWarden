# IsleWarden server (Python)

The IsleWarden server: access gates, player login, leases, the game-server whitelist, scan reports and the
admin dashboard. It is built on FastAPI and uvicorn, with SQLite from the standard library. The launcher
(`IsleWarden.Agent`) is C# and talks to it over HTTP.

Until 26 September 2026 the server was C# (the `IsleWarden.Server` project). This is a port with the same HTTP API,
the same SQLite schema and the same settings, checked response by response against the C# server before it
was removed; the C# code is kept outside the repository in
`C:\Users\Bao\Projects\IsleWarden-archive\2026-09-26-csharp-server`. A deployment of the C# server can switch
to this one with its existing settings and database (see [Moving from the C# server](#moving-from-the-c-server)).

## Requirements

Python 3.10 or newer (tested on 3.12 and 3.13), on Windows or Linux. No .NET runtime is needed.

## Quick start

From this folder:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python -m islewarden_server --dev        # Windows: .venv\Scripts\python -m islewarden_server --dev
```

`--dev` also loads `appsettings.Development.json`, which sets the admin key to `iw-local-test`, makes new
devices wait for approval, and turns the Discord requirement off so players sign in with Steam alone. Open
http://localhost:5088/admin/ and sign in with that key. The rest of the walkthrough (the launcher's `login`,
then `play`) is the same as in the main README's quick start.

## Running

```text
python -m islewarden_server [--config appsettings.json] [--dev] [--host 127.0.0.1] [--port 5088] [--access-log]
```

| Option | Default | Meaning |
|---|---|---|
| `--config` | `appsettings.json` in the current directory | Settings file. A missing default file just means defaults; a missing `--config` file is an error. |
| `--dev` | off | Also load `appsettings.Development.json` next to the settings file. Local testing only. |
| `--host` | `127.0.0.1` | Address to listen on. Keep it local and put a reverse proxy with HTTPS in front. |
| `--port` | `5088` | Port to listen on. |
| `--access-log` | off | Log every HTTP request. Off by default because every launcher sends a heartbeat every 30 s. |

Relative paths in the settings (`DatabasePath`, `PolicyPath`, `BaselineDirectory`, `Whitelist.FilePath`)
are resolved against the current directory, as with the C# server.

## Configuration

Exactly as for the C# server: the `IsleWarden` section of `appsettings.json`, overridden by environment
variables named `IsleWarden__<Key>`, with `__` between nested keys (`IsleWarden__Whitelist__RconPassword`).
Keys match case-insensitively. The keys and their defaults are listed under *Server settings* in the main
[README](../README.md#server-settings). An invalid value (for example `HeartbeatSeconds=abc`) stops the server
at startup with a message naming the key.

Set the secrets through the environment rather than the file:

```bash
export IsleWarden__AdminKey='<long random string>'
export IsleWarden__FingerprintPepper='<long random string, never change it>'
```

The policy served to launchers is `server-policy.json` (see `PolicyPath`). Comments and trailing commas are
allowed. The file is reloaded when it changes; an edit that doesn't parse is logged and the last good policy
stays in use.

### Player login

Players sign in from the launcher with Steam, then with Discord. Only a member of your Discord server who holds
one of the required roles gets a device key, and the role is re-checked while they play. A real server needs:

| Key | Meaning |
|---|---|
| `PublicUrl` | This server's address as players' browsers reach it, e.g. `https://ac.example.com`. Steam and Discord send the browser back here. |
| `Discord.Required` | `true` by default. `false` means Steam-only login, for local testing. |
| `Discord.ClientId`, `Discord.ClientSecret` | The Discord application players sign in with. Register `<PublicUrl>/login/discord/callback` as its redirect URL. |
| `Discord.BotToken` | The same application's bot, added to your Discord server; it only reads members' roles. |
| `Discord.GuildId` | Your Discord server's ID. |
| `Discord.RequiredRoleIds` | Role IDs allowed to play; holding any one is enough. Empty means any member. In environment variables: `IsleWarden__Discord__RequiredRoleIds__0`, `__1`, ... |
| `Discord.RoleRecheckMinutes` | How often a playing member's role is checked again (default 10). |

The server logs an error at startup for each missing Discord key. When Discord can't be reached, players keep
the result of their last successful role check, so an outage doesn't lock everyone out. Logins in progress
live in memory for 10 minutes; a restart only means an unfinished login has to be started again.

## Deploying on Linux

A systemd unit, assuming the folder is in `/opt/islewarden/server` with its virtual environment in `.venv`:

```ini
[Unit]
Description=IsleWarden server
After=network.target

[Service]
WorkingDirectory=/opt/islewarden/server
ExecStart=/opt/islewarden/server/.venv/bin/python -m islewarden_server --host 127.0.0.1 --port 5088
Environment=IsleWarden__AdminKey=change-me
Environment=IsleWarden__FingerprintPepper=change-me-once
Environment=IsleWarden__PublicUrl=https://ac.example.com
# plus the Discord keys from "Player login", e.g. IsleWarden__Discord__BotToken=...
Restart=on-failure
User=islewarden

[Install]
WantedBy=multi-user.target
```

Then put nginx or Caddy in front with HTTPS, and restrict `/admin/` and `/api/admin/` to your admins. The
production checklist in the main README applies unchanged.

## Moving from the C# server

1. Stop the C# server.
2. Copy `appsettings.json`, `server-policy.json`, the database (with its `-wal` and `-shm` files, if present)
   and the baselines folder next to this server, keeping the same relative paths.
3. Start this server from that folder.

Nothing else changes: launchers keep their device keys and leases, bans and hardware bans keep matching
(hashes use the same format and pepper), and the dashboard keeps its URL.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The suite ports every test of the C# server's test project and adds HTTP-level tests of the JSON shapes
the launcher and the dashboard rely on. `tests/fake_rcon.py` speaks EVRIMA's binary RCON protocol, so the
exact bytes sent to the game server are checked. `FakeLoginServices` in `tests/helpers.py` stands in for
Steam and the Discord API, so the whole login runs offline.

To watch RCON traffic by hand, run the mock server and point the whitelist bridge at it:

```bash
python tools/mock_rcon.py --port 8888 --password secret
```

```bash
export IsleWarden__Whitelist__Mode=rcon
export IsleWarden__Whitelist__RconHost=127.0.0.1
export IsleWarden__Whitelist__RconPort=8888
export IsleWarden__Whitelist__RconPassword=secret
```

## Layout

| Module | Role (C# counterpart) |
|---|---|
| `app.py` | Routes, admin key check, static files (`Program.cs`, `Endpoints/*`) |
| `login/` | Steam OpenID, Discord OAuth and role checks, logins in progress, the login flow (`Services/Login/*`) |
| `sessions.py` | Device registration, the access gates, leases (`SessionManager`) |
| `access.py` | Gates, stable block codes and the wording players see (`AccessBlocks`, `Protocol/Access.cs`) |
| `store.py`, `dashboard.py`, `db.py` | Data access, dashboard queries, schema and migrations (`Data/*`) |
| `whitelist.py`, `rcon.py` | Whitelist sync in none/rcon/file mode, EVRIMA RCON client |
| `policy.py` | Policy reload and baselines (`PolicyProvider`) |
| `risk.py` | Risk score for the review queue (`RiskScorer`) |
| `sweeper.py` | Expires leases whose heartbeats stopped (`SessionSweeper`) |
| `discord.py` | Discord webhook alerts (`DiscordNotifier`) |
| `models.py` | Request bodies, policy and baseline models (`IsleWarden.Core`) |
| `settings.py` | `appsettings.json` and `IsleWarden__*` variables (`ServerOptions`) |
| `static/` | `consent.html` and the built dashboard, served at `/consent.html` and `/admin/` |

Endpoints are plain functions that FastAPI runs on a thread pool, because SQLite, RCON and the webhook are
all blocking calls. Each database operation opens its own connection; the database runs in WAL mode.

## Keeping it in step with the launcher and the dashboard

The server shares no code with the C# launcher, only the HTTP protocol, so these must be changed together
with their counterpart:

- `models.py` mirrors the launcher protocol and policy records in `launcher/IsleWarden.Core`, and
  `FINDING_CODES` mirrors `FindingCodes.cs`. `access.py` mirrors `AccessCodes` and `LoginCodes`, and
  `crypto.pkce_challenge` must compute exactly what the launcher's `Pkce.Challenge` does.
- The JSON returned to the dashboard mirrors `dashboard/src/types.ts`.
- `islewarden_server/static/admin` is the dashboard build: `npm run build` in `dashboard/` writes it there
  directly. Don't edit it by hand.

## Differences from the C# server

Behavior is the same; the differences are where the C# server failed badly or silently:

- A malformed request body gets `400 {"error": "..."}`. The C# server answered 400 or 500 depending on
  what was missing.
- `POST /api/admin/bans` rejects a `subjectType` other than `steam_id`, `device` or `component`, instead of
  storing a ban that can never match.
- `PUT /api/admin/baselines/{buildId}` rejects a file that isn't a valid baseline, and writes atomically.
  Build IDs are limited to ASCII letters, digits, `.`, `-` and `_`.
- `GET /api/admin/devices?status=` with an unknown status gets 400 instead of 500.
- A 401 from the admin API carries a short message.
- A policy edit that doesn't parse is logged once per edit, not on every request.
- Times sent with a non-UTC offset (for example a ban's `expiresUtc`) are stored in UTC, so string
  comparisons in SQL stay correct.
- Request bodies over 30 MB are refused with 413, matching Kestrel's default limit.
- Behind a reverse proxy on the same machine, uvicorn honours `X-Forwarded-Proto`, so without `PublicUrl`
  the login return URL still gets the right scheme. Set `PublicUrl` anyway.
