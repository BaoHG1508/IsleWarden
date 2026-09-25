// Hand-maintained TypeScript copies of the server DTOs. Sources: Server/Data/DashboardStore.cs (dashboard DTOs),
// Server/Data/Entities.cs (DeviceRecord, SessionRecord, BanRecord, BypassRecord, DiscordLinkRecord), Server/Services/RiskScorer.cs
// (RiskAssessment, RiskOptions), Core (Severity, Finding) and the anonymous object returned by /config in
// Server/Endpoints/AdminDashboardApi.cs (ServerConfig). The server writes camelCase and camelCase enum strings —
// hence "approved", "high", "clean". Change a DTO in C# and change it here too.

export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical'
export type RiskBand = 'clean' | 'low' | 'medium' | 'high'
export type DeviceStatus = 'pending' | 'approved' | 'rejected'
export type SessionState = 'active' | 'revoked' | 'expired' | 'ended'
export type DiscordRoleState = 'ok' | 'notMember' | 'roleMissing'

export const SEVERITIES: Severity[] = ['info', 'low', 'medium', 'high', 'critical']

export interface Overview {
  activeSessions: number
  playersLast24h: number
  reportsLast24h: number
  findingsLast24h: Partial<Record<Severity, number>>
  pendingDevices: number
  activeBans: number
  whitelisted: number
  highRiskPlayers: number
  reportCount: number
  oldestReportUtc: string | null
  databaseBytes: number
}

export interface PlayerSummary {
  steamId: string
  score: number
  band: RiskBand
  reasons: string[]
  lastSeenUtc: string | null
  sessions: number
  devices: number
  banned: boolean
  whitelisted: boolean
  watched: boolean
  bypassed: boolean
  discordName: string | null
}

export interface RiskAssessment {
  score: number
  band: RiskBand
  reasons: string[]
}

export interface FlaggedSoftware {
  code: string
  severity: Severity
  message: string
  detail: string | null
  hits: number
  firstUtc: string
  lastUtc: string
}

export interface FindingGroup {
  code: string
  severity: Severity
  rank: number
  hits: number
  days: number
  firstUtc: string
  lastUtc: string
}

export interface DeviceRecord {
  deviceId: string
  steamId: string
  deviceKeyHash: string
  machineName: string
  fingerprintId: string | null
  status: DeviceStatus
  consentVersion: string
  createdUtc: string
  /** Risk flag that held the device for review despite auto-approval. */
  reviewReason: string | null
}

export interface SessionRecord {
  sessionId: string
  deviceId: string
  steamId: string
  tokenHash: string
  state: SessionState
  startedUtc: string
  expiresUtc: string
  lastHeartbeatUtc: string
  endedUtc: string | null
  /** Why the lease ended — an access code such as "lease-expired" or "anticheat-blocked". */
  endCode: string | null
  endReason: string | null
}

export interface BanRecord {
  id: number
  subjectType: 'steam_id' | 'device' | 'component'
  subjectValue: string
  reason: string | null
  createdUtc: string
  expiresUtc: string | null
}

export interface BypassRecord {
  steamId: string
  reason: string
  createdUtc: string
  expiresUtc: string | null
}

export interface DiscordLink {
  steamId: string
  discordId: string
  discordName: string
  linkedUtc: string
  /** Result of the last successful role check (reused while Discord is unreachable). */
  roleState: DiscordRoleState
  checkedUtc: string
}

export interface AdminAction {
  id: number
  action: string
  subjectType: string
  subjectValue: string
  note: string | null
  reportId: number | null
  createdUtc: string
}

export interface PlayerDetail {
  steamId: string
  risk: RiskAssessment
  banned: boolean
  whitelisted: boolean
  watched: boolean
  /** Present even when expired, so it can be renewed or removed. */
  bypass: BypassRecord | null
  discord: DiscordLink | null
  devices: DeviceRecord[]
  sessions: SessionRecord[]
  findings: FindingGroup[]
  software: FlaggedSoftware[]
  bans: BanRecord[]
  actions: AdminAction[]
}

export interface ReportSummary {
  id: number
  receivedUtc: string
  steamId: string
  deviceId: string
  sessionId: string
  clean: boolean
  findingCount: number
  worstRank: number
  topCode: string | null
}

export interface Finding {
  code: string
  severity: Severity
  message: string
  detail: string | null
}

export interface ReportDetail {
  summary: ReportSummary
  findings: Finding[]
  /** Only present with ?processes=true — and that request is written to the admin log. */
  processes: string[] | null
}

export interface RiskOptions {
  windowDays: number
  halfLifeDays: number
  lowWeight: number
  mediumWeight: number
  highWeight: number
  criticalWeight: number
  lowCeiling: number
  mediumCeiling: number
}

export interface ServerConfig {
  mode: string
  disclosureVersion: string
  enforceThreshold: string
  heartbeatSeconds: number
  leaseGraceSeconds: number
  autoApproveDevices: boolean
  allowBypass: boolean
  whitelistMode: string
  kickOnRevoke: boolean
  kickWithoutLease: boolean
  kickGraceSeconds: number
  discordRequired: boolean
  discordGuildId: string | null
  discordRoleIds: string[]
  discordRecheckMinutes: number
  risk: RiskOptions
  codes: string[]
}

export type BanScope = 'steam' | 'device' | 'all'
