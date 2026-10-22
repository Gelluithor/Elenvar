export type Role = "viewer" | "operator" | "admin";

export interface User {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  totp_enabled: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
}

export type Stage = "mfa" | "enroll" | "full";

export interface SessionPayload {
  stage: Stage;
  csrf_token: string;
  user?: User;
  username?: string;
  require_2fa?: boolean;
  recovery_codes_left?: number;
  recovery_codes_exhausted?: boolean;
}

export interface Disk {
  id: string;
  kind: string;
  name: string;
  status: string;
  capacity_mb: number;
  free_mb: number;
  property: string;
}

export type NvrStatus = "unknown" | "online" | "offline" | "auth_error" | "error" | "disabled";

export interface Nvr {
  id: number;
  name: string;
  enabled: boolean;
  status: NvrStatus;
  status_message: string;
  status_changed_at: string | null;
  last_seen_at: string | null;
  last_poll_at: string | null;
  model: string;
  device_type: string;
  device_name: string;
  firmware: string;
  serial_number: string;
  device_time: string;
  time_drift_sec: number | null;
  camera_count: number;
  camera_online: number;
  camera_monitored_offline: number;
  disks: Disk[];
  disk_problems: string[];
  transcode: boolean;
  host?: string;
  http_port?: number;
  rtsp_port?: number;
  use_https?: boolean;
  verify_tls?: boolean;
  username?: string;
  notes?: string;
  mac_address?: string;
  cameras?: Camera[];
}

export type CameraState = "online" | "offline" | "unknown" | "nvr_down";

export interface Camera {
  id: number;
  nvr_id: number;
  nvr_name: string;
  channel: number;
  name: string;
  ip_address: string;
  online: boolean | null;
  state: CameraState;
  detail: string;
  monitored: boolean;
  status_changed_at: string | null;
  last_online_at: string | null;
}

export type Severity = "info" | "warning" | "critical";

export interface EventItem {
  id: number;
  ts: string;
  severity: Severity;
  kind: string;
  nvr_id: number | null;
  nvr_name: string;
  camera_id: number | null;
  message: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
}

export interface Problem {
  severity: "critical" | "warning";
  kind: "nvr" | "disk" | "time" | "camera";
  nvr_id: number;
  camera_id?: number;
  title: string;
  message: string;
  since: string | null;
}

export interface Dashboard {
  nvr_total: number;
  nvr_online: number;
  camera_total: number;
  camera_online: number;
  monitored_total: number;
  monitored_online: number;
  unacknowledged_events: number;
  problems: Problem[];
}

export interface Segment {
  start: string;
  end: string;
  type: string;
}

export interface AdminUser {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  totp_enabled: boolean;
  must_change_password: boolean;
  locked: boolean;
  failed_attempts: number;
  created_at: string;
  last_login_at: string | null;
}

export interface AppSettings {
  require_2fa: boolean;
  poll_interval: number;
  offline_threshold: number;
  time_drift_threshold: number;
  event_retention_days: number;
  audit_retention_days: number;
  smtp_enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_security: "starttls" | "ssl" | "none";
  smtp_username: string;
  smtp_password_set: boolean;
  smtp_from: string;
  smtp_to: string;
  webhook_enabled: boolean;
  webhook_url: string;
  notify_recoveries: boolean;
  update_check_enabled: boolean;
  update_include_prereleases: boolean;
  language: "cs" | "en";
}

export interface AuditEntry {
  id: number;
  ts: string;
  username: string;
  ip: string;
  action: string;
  detail: string;
  success: boolean;
}

export interface SessionInfo {
  id: number;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  ip: string;
  user_agent: string;
  current: boolean;
}

export interface StreamSettings {
  current: Record<string, string | number>;
  options: Record<string, string[]>;
  ranges: Record<string, [number, number]>;
  resolutions: [number, number][];
}
