import type { Role } from "../types";
import { locale, N_, t } from "./i18n";

const formatters = new Map<string, { dateTime: Intl.DateTimeFormat; timeOnly: Intl.DateTimeFormat }>();

/** Formátovače data a času pro aktuální jazyk (vytvořené jednou na jazyk). */
function fmt() {
  const key = locale();
  let entry = formatters.get(key);
  if (!entry) {
    entry = {
      dateTime: new Intl.DateTimeFormat(key, {
        day: "numeric",
        month: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }),
      timeOnly: new Intl.DateTimeFormat(key, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }),
    };
    formatters.set(key, entry);
  }
  return entry;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : fmt().dateTime.format(date);
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 0) return fmt().dateTime.format(date);
  if (seconds < 45) return t("právě teď");
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return t("před {minutes} min", { minutes: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t("před {hours} h", { hours: hours });
  const days = Math.round(hours / 24);
  if (days === 1) return t("před 1 dnem");
  if (days < 30) return t("před {days} dny", { days });
  return fmt().dateTime.format(date);
}

/** Naivní čas zařízení "YYYY-MM-DDTHH:MM:SS" (bez převodu časových zón). */
export function parseDeviceTime(value: string): Date {
  const [datePart, timePart] = value.split("T");
  const [y, m, d] = datePart.split("-").map(Number);
  const [hh, mm, ss] = (timePart ?? "00:00:00").split(":").map(Number);
  return new Date(y, m - 1, d, hh, mm, ss);
}

export function toDeviceTime(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}

export function formatClock(date: Date): string {
  return fmt().timeOnly.format(date);
}

export function todayIso(): string {
  return toDeviceTime(new Date()).slice(0, 10);
}

export function formatBytesMb(mb: number): string {
  if (mb >= 1024 * 1024) return `${(mb / 1024 / 1024).toFixed(1)} TB`;
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb} MB`;
}

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = s % 60;
  if (h > 0) return `${h} h ${m} min`;
  if (m > 0) return `${m} min ${rest} s`;
  return `${rest} s`;
}

export const ROLE_LABELS: Record<Role, string> = {
  viewer: N_("Pozorovatel"),
  operator: N_("Operátor"),
  admin: N_("Administrátor"),
};

const ROLE_RANK: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

export function hasRole(role: Role | undefined, minimum: Role): boolean {
  if (!role) return false;
  return ROLE_RANK[role] >= ROLE_RANK[minimum];
}

export const RECORD_TYPE_LABELS: Record<string, string> = {
  timing: N_("Průběžný"),
  motion: N_("Pohyb"),
  alarm: N_("Alarm"),
  manual: N_("Ruční"),
  AllEvent: N_("Událost"),
  allevent: N_("Událost"),
  smart: N_("Smart"),
  vca: N_("Analytika"),
  linedetection: N_("Překročení čáry"),
  fielddetection: N_("Vniknutí"),
};
