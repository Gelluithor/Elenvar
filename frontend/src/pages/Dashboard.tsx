import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Activity, BellRing, Camera, CircleCheck, Clock, HardDrive, Server, TriangleAlert, Video } from "lucide-react";
import { Alert, EmptyState, NvrStatusPill, PageHeader, PageLoader, usePolling } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { formatRelative } from "../lib/format";
import type { Dashboard, Nvr, Problem } from "../types";
import { t } from "../lib/i18n";

function StatCard({
  icon,
  label,
  value,
  total,
  tone,
  to,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  total?: number;
  tone: "ok" | "warn" | "bad" | "neutral";
  to?: string;
}) {
  const body = (
    <>
      <div className={`stat-icon tone-${tone}`}>{icon}</div>
      <div className="stat-body">
        <span className="stat-label">{label}</span>
        <span className="stat-value">
          {value}
          {total !== undefined && <span className="stat-total"> / {total}</span>}
        </span>
      </div>
    </>
  );
  return to ? (
    <Link to={to} className="stat-card">
      {body}
    </Link>
  ) : (
    <div className="stat-card">{body}</div>
  );
}

function ratioTone(value: number, total: number): "ok" | "warn" | "bad" | "neutral" {
  if (total === 0) return "neutral";
  if (value === total) return "ok";
  if (value === 0) return "bad";
  return "warn";
}

const PROBLEM_ICON: Record<Problem["kind"], ReactNode> = {
  nvr: <Server size={18} />,
  camera: <Camera size={18} />,
  disk: <HardDrive size={18} />,
  time: <Clock size={18} />,
};

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [nvrs, setNvrs] = useState<Nvr[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [d, n] = await Promise.all([api<Dashboard>("/api/dashboard"), api<Nvr[]>("/api/nvrs")]);
      setData(d);
      setNvrs(n);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  usePolling(() => void load(), 15000);

  if (!data) return error ? <Alert>{error}</Alert> : <PageLoader />;

  return (
    <div className="page">
      <PageHeader title={t("Přehled")} subtitle={t("Aktuální stav všech zařízení a kamer")} />
      {error && <Alert>{error}</Alert>}

      <section className="stats">
        <StatCard icon={<Server size={20} />} label={t("Zařízení online")} value={data.nvr_online} total={data.nvr_total} tone={ratioTone(data.nvr_online, data.nvr_total)} to="/devices" />
        <StatCard icon={<Video size={20} />} label={t("Kamery online")} value={data.camera_online} total={data.camera_total} tone={ratioTone(data.camera_online, data.camera_total)} to="/live" />
        <StatCard icon={<Activity size={20} />} label={t("Sledované kamery v pořádku")} value={data.monitored_online} total={data.monitored_total} tone={ratioTone(data.monitored_online, data.monitored_total)} to="/monitoring" />
        <StatCard icon={<BellRing size={20} />} label={t("Nepotvrzené události")} value={data.unacknowledged_events} tone={data.unacknowledged_events ? "warn" : "ok"} to="/monitoring" />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>{t("Aktuální problémy")}</h2>
          <Link to="/monitoring" className="link">
            {t("Historie událostí")}
          </Link>
        </div>
        {data.problems.length === 0 ? (
          <div className="all-good">
            <CircleCheck size={22} />
            <div>
              <strong>{t("Vše v pořádku")}</strong>
              <span>{t("Všechna zařízení a sledované kamery fungují.")}</span>
            </div>
          </div>
        ) : (
          <ul className="problem-list">
            {data.problems.map((p, i) => (
              <li key={`${p.kind}-${p.nvr_id}-${p.camera_id ?? i}`} className={`problem problem-${p.severity}`}>
                <span className="problem-icon">{PROBLEM_ICON[p.kind]}</span>
                <div className="problem-text">
                  <Link to={`/devices/${p.nvr_id}`}>
                    <strong>{p.title}</strong>
                  </Link>
                  <span>{p.message}</span>
                </div>
                {p.since && <span className="problem-since">{formatRelative(p.since)}</span>}
                {p.severity === "critical" ? <TriangleAlert size={18} className="tone-bad-text" /> : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>{t("Zařízení")}</h2>
        </div>
        {nvrs.length === 0 ? (
          <EmptyState icon={<Server size={28} />} title={t("Zatím žádná zařízení")}>
            {t("Přidejte první NVR v sekci")} <Link to="/devices">{t("Zařízení")}</Link>.
          </EmptyState>
        ) : (
          <div className="nvr-grid">
            {nvrs.map((n) => (
              <Link key={n.id} to={`/devices/${n.id}`} className="nvr-card">
                <div className="nvr-card-head">
                  <strong>{n.name}</strong>
                  <NvrStatusPill status={n.status} />
                </div>
                <div className="nvr-card-model">{n.model || "—"}</div>
                <div className="nvr-card-stats">
                  <span title={t("Kamery online")}>
                    <Video size={15} /> {n.camera_online}/{n.camera_count}
                  </span>
                  <span title={t("Disky")} className={n.disk_problems.length ? "tone-bad-text" : ""}>
                    <HardDrive size={15} /> {n.disk_problems.length ? t("Problém") : n.disks.length ? "OK" : "—"}
                  </span>
                  <span title={t("Naposledy dostupné")}>
                    <Clock size={15} /> {formatRelative(n.last_seen_at)}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
