# IsleWarden: what a server admin needs to know

You run a *The Isle: EVRIMA* server and you're going to deploy IsleWarden, or fold its code into your
own setup. This guide covers what matters, in the order you need it. The [reference](REFERENCE.md)
has everything in full; this page tells you which parts of it you can't skip.

## 1. The system in one minute

```text
 Discord (role = allowed to play)      Steam (proves the Steam ID)
            │                                   │
            ▼                                   ▼
 Player's PC: IsleWarden.Agent  ──HTTPS──►  IsleWarden.Server  ──RCON──►  your EVRIMA server
   login (once) → play                    gates, leases, bans           whitelist add / remove
   scans + heartbeats every 30 s          dashboard at /admin/          (bServerWhitelist=true)
```

A player gets in like this:

1. They join your Discord server and **you give them the play role**. That role is how you decide
   who may play. There are no invite codes.
2. They run `IsleWarden.Agent login` once. The browser opens: Steam sign-in, then Discord sign-in.
   The server checks the role and gives the launcher a device key.
3. Each time they play, they run `IsleWarden.Agent play --launch` and keep it open. The server checks
   the gates in order (**device → ban → Discord role → consent → anti-cheat**), grants a lease, and
   adds their Steam ID to the game's whitelist over RCON.
4. Every 30 s the launcher rescans and renews the lease. When they quit, when heartbeats stop for
   75 s, when they lose the role, get banned or (in `enforce` mode) trip the scanner, the lease ends
   and their Steam ID leaves the whitelist.

**The game whitelist is the only enforcement.** With `bServerWhitelist=true`, EVRIMA refuses anyone
who isn't on it. IsleWarden never touches the player's PC; it only decides who stays on the list.

## 2. Setup checklist

Do these in order. Each item links to the details.

| # | Task | Details |
|---|---|---|
| 1 | Set up `Game.ini`: `bServerWhitelist=true` and RCON on, in the **right sections** (a key in the wrong one is silently ignored). Put staff Steam IDs in `WhitelistIDs=` so they can always get in. Firewall the RCON port. | Reference → [Connecting to an EVRIMA server](REFERENCE.md#connecting-to-an-evrima-server) |
| 2 | Create the Discord application, invite its bot, copy the server ID and the play role's ID. | Reference → [Set up Discord login](REFERENCE.md#set-up-discord-login) |
| 3 | Set the server settings, with secrets in environment variables: `PublicUrl`, `AdminKey`, `FingerprintPepper`, `Whitelist.*` (mode `rcon`), `Discord.*`. | Reference → [Server settings](REFERENCE.md#server-settings) |
| 4 | Put the server behind HTTPS. Restrict `/admin/` and `/api/admin/` to admin IPs or behind extra auth. | Reference → [Run the server](REFERENCE.md#run-the-server) |
| 5 | Edit `server-policy.json`: keep `mode: "observe"`, write the `disclosure` for *your* players and in their language, choose the blocked tools. | Reference → [Policy](REFERENCE.md#policy) |
| 6 | Build a release with `build-release.ps1` and code-sign the launcher. | Reference → [Build a release](REFERENCE.md#build-a-release) |
| 7 | Upload a baseline for the current game build. Repeat after every EVRIMA update. | Reference → [Baselines](REFERENCE.md#baselines-for-each-game-build) |
| 8 | Run the 13-step real-server test before inviting players. Steps 7, 8, 9 and 13 matter most. | Reference → [Testing, level 2](REFERENCE.md#level-2-a-real-evrima-server) |

## 3. Decisions you have to make

| Setting | Recommendation | Why |
|---|---|---|
| `Discord.RequiredRoleIds` | One dedicated role, for example "Whitelisted" | Granting and removing that role is how you let people in and out. |
| policy `mode` | `observe` for 1–2 weeks, then `enforce` | Measure false positives on the dashboard before anything blocks. |
| `EnforceThreshold` | `High` | Keyword and "tool on disk" heuristics are `low`/`medium` on purpose; they are hints, not proof. |
| `AutoApproveDevices` | `true` for a small server | Risky devices (shared hardware with another or banned account, no fingerprint) still wait for review. |
| `Whitelist.KickOnRevoke` | `false` until test steps 8–9 pass | The RCON kick opcode (`0x30`) is not verified on a real server. |
| `FingerprintPepper` | Long random value, set once | Changing it later silently breaks every hardware ban. |
| `executionHistory` in the policy | Off at first | Needs admin rights on the player's PC and must be in the disclosure. |
| `overlayScan` in the policy | On, at `medium`, with the example allowlist | During `observe`, check `foreign-overlay` on the dashboard and add legitimate overlays your players use to `allowedProcesses`. |
| `Discord.WebhookUrl` | A staff-only channel | Alerts for findings, blocked bans, revoked leases, devices needing review. |

## 4. Where things live in the code

The launcher and its scanners are C# (`launcher/`); the server is Python (`server/islewarden_server/`,
paths below are relative to it unless they start with `launcher/` or `dashboard/`).

| To change or understand… | Read |
|---|---|
| Who may join, and when a lease ends | `sessions.py` (`start_session`, `heartbeat`) |
| The wording and codes a blocked player sees | `access.py` on the server, `launcher/IsleWarden.Core/Protocol/Access.cs` in the launcher |
| Steam + Discord login | `login/service.py` (flow), `login/steam.py`, `login/discord_api.py`, the `/login/*` routes in `app.py`; protocol and its security notes in `launcher/IsleWarden.Core/Protocol/Login.cs`; launcher side in `launcher/IsleWarden.Agent/LoginCommand.cs` and `LoopbackListener.cs` |
| The Discord role check | `login/discord_gate.py` |
| Whitelist sync and RCON | `whitelist.py`, `rcon.py` |
| Lease expiry after lost heartbeats | `sweeper.py` |
| What the launcher scans | `launcher/IsleWarden.Core/Scanner.cs` (runs everything), `Policy.cs` (the policy schema), one file per scanner |
| Launcher commands | `launcher/IsleWarden.Agent/*Command.cs` |
| Database schema and queries | `db.py` (schema and migrations), `store.py`, `dashboard.py` |
| Dashboard | `dashboard/src`; `types.ts` must mirror the JSON in `records.py` and `dashboard.py` |
| Settings | `settings.py`, `appsettings.json` |

Build and test the launcher with `dotnet build launcher/IsleWarden.slnx` and `dotnet test launcher/IsleWarden.slnx`; test the
server with `python -m pytest` in `server/` (see [server/README.md](../server/README.md)).

## 5. Plugging it into your own system

- **You already manage members elsewhere** (your own bot, database or website). The only place that
  decides "is this person allowed" is `DiscordGate` in `server/islewarden_server/login/discord_gate.py`:
  `check()` returns a block or `None`. Replace its Discord lookup with your source and keep the contract.
  Login (`login/service.py`) calls the same gate.
- **You already manage the EVRIMA whitelist another way.** Don't let two tools push the same RCON
  whitelist; they will undo each other. Either let IsleWarden own it, or use `Whitelist.Mode = file`
  and feed that list into your tool. `WhitelistBridge` in `whitelist.py` is the single place that writes
  out.
- **You have your own launcher.** `IsleWarden.Core` is a standalone library: build a `Policy`, call
  `new Scanner().Run(policy)` and you get a `ScanReport`. The launcher ↔ server contract is the set
  of records in `launcher/IsleWarden.Core/Protocol`.
- **You only want the scanner, no server.** `IsleWarden.Agent scan policy.json` works offline.

## 6. Rules that must not break

These are deliberate. If you change the code, keep them:

1. **Secrets are stored only as hashes.** That covers device keys and lease tokens. Hardware
   identifiers are HMAC'd with `FingerprintPepper`; raw serials are never written to disk.
2. **An outage of RCON or Discord never locks everyone out.** RCON down: leases are still granted
   and the error is logged. Discord down: the last known role result is used. A game server on the
   wrong port must not become a server-wide outage.
3. **Released codes never change.** `AccessCodes`, `FindingCodes` and `LoginCodes` values are read by
   the launcher, the dashboard and stored data. Add new ones; never rename.
4. **Privacy.** The process inventory sends names only (no paths, command lines or window titles).
   Scanners match by name or hash *before* reading anything and never record non-matches. Everything
   collected is in the disclosure; changing what's collected means bumping `disclosureVersion`.
5. **Report data is untrusted.** It comes from the player's PC. Never render it as HTML in the
   dashboard; a crafted file name would be an XSS hole.
6. **Every admin action is logged** in `admin_actions`. Viewing a player's process list is an action.
7. **The risk score never blocks anyone.** Only `EnforceThreshold` or an admin blocks.
8. **An anti-cheat bypass relaxes only two things:** the anti-cheat gate and device approval. It never
   relaxes bans, rejected devices, the Discord role or consent.
9. **Lease endings never use anti-cheat codes.** A player who lost connection must not be told
   they're suspected of cheating.
10. **The wire shapes have three copies**: the launcher's records in `launcher/IsleWarden.Core/Protocol`, the
    server's models in `server/islewarden_server/`, and `dashboard/src/types.ts`. Change them together.

## 7. What isn't verified, and known weak spots

Be honest with your community about these:

- **RCON:** the opcodes come from public EVRIMA libraries and are tested against a byte-accurate
  mock, not a live server. It's unknown whether removing someone from the whitelist disconnects a
  player who is already in. The optional kick (`0x30`) is unverified too. Test steps 8–9 answer both.
- **The RCON whitelist lives only in the game server's memory.** After a game-server restart, players
  must close and reopen the launcher to get back on.
- **Steam and Discord login** are tested against fakes of both services. Do one real login with your
  own Discord application before inviting players.
- **Nothing ties the game to the launcher's PC yet.** A clean PC could hold the lease while the same
  Steam account plays from another PC. The fix is on the roadmap: check the Steam account logged in
  on the PC (`HKCU\Software\Valve\Steam\ActiveProcess\ActiveUser`), and require the game process
  during the lease. Until then, treat this as the most important known gap.
- **The launcher can be imitated.** A re-implemented launcher could send clean reports; a per-scan
  challenge is on the roadmap.
- **User mode only.** Kernel cheats, DMA hardware and spoofed hardware IDs are out of reach. Keep
  EasyAntiCheat on.
- **The disclosure must match reality.** At login the launcher sends raw hardware identifiers, which
  the server hashes on arrival. The example disclosure only says "a hashed machine identifier";
  reword yours.
- **`server/islewarden_server/static/admin.html` is an old, unmaintained copy of the dashboard** that is
  still served at `/admin.html`. Delete it or block it at the proxy.

## 8. Day-to-day operations

| Situation | What to do |
|---|---|
| New player | Give them the play role in Discord. They run `login` once, then `play --launch`. |
| Remove someone quickly | Ban them on their dashboard profile: immediate. Removing the role takes effect at the next re-check (up to `RoleRecheckMinutes`). |
| Player changed Discord or Steam account | Profile → Discord → *Unlink*, then they run `login` again. |
| Streamer keeps getting flagged by capture tools | Profile → grant an anti-cheat bypass with a reason and an end date. |
| A device is waiting for review | **Devices** tab: the reason is shown (for example hardware shared with a banned account). |
| EVRIMA update | Build and upload a new baseline for the new build ID. |
| Player appeals a block | They quote the support code: `R-123` is scan report 123 (`/admin/#/reports/123`), `B-45` is ban 45. |
| Database growing | Maintenance tab → prune old reports; ban evidence is kept as a summary. |
