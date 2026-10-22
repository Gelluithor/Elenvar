import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Check, CheckCheck, CircleCheck } from "lucide-react";
import { useAuth } from "../auth";
import { Alert, PageHeader, PageLoader, SeverityPill, Spinner, usePolling, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { formatDateTime, formatRelative, hasRole } from "../lib/format";
import type { Dashboard, EventItem, Severity } from "../types";
import { t } from "../lib/i18n";

const PAGE = 100;

export function MonitoringPage() {
  const { user } = useAuth();
  const toast = useToast();
  const canAck = hasRole(user?.role, "operator");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [events, setEvents] = useState<EventItem[] | null>(null);
  const [severity, setSeverity] = useState<Severity | "">("");
  const [unackedOnly, setUnackedOnly] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query = useCallback(
    (beforeId?: number) => {
      const p = new URLSearchParams({ limit: String(PAGE) });
      if (severity) p.set("severity", severity);
      if (unackedOnly) p.set("unacknowledged", "true");
      if (beforeId) p.set("before_id", String(beforeId));
      return `/api/events?${p.toString()}`;
    },
    [severity, unackedOnly],
  );

  const extraLoaded = useRef(false);

  const load = useCallback(async () => {
    try {
      const [d, e] = await Promise.all([api<Dashboard>("/api/dashboard"), api<EventItem[]>(query())]);
      setDashboard(d);
      setEvents((prev) => {
        // Při obnovování ponechat již načtené starší stránky.
        if (!prev || !extraLoaded.current) return e;
        const oldest = e.length ? e[e.length - 1].id : Number.POSITIVE_INFINITY;
        return [...e, ...prev.filter((x) => x.id < oldest)];
      });
      if (!extraLoaded.current) setHasMore(e.length === PAGE);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [query]);

  useEffect(() => {
    extraLoaded.current = false;
    setEvents(null);
    void load();
  }, [load]);
  usePolling(() => void load(), 20000);

  const loadMore = async () => {
    if (!events?.length) return;
    setLoadingMore(true);
    try {
      const more = await api<EventItem[]>(query(events[events.length - 1].id));
      extraLoaded.current = true;
      setEvents((prev) => [...(prev ?? []), ...more]);
      setHasMore(more.length === PAGE);
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setLoadingMore(false);
    }
  };

  const ack = async (id: number) => {
    try {
      await api(`/api/events/${id}/ack`, { method: "POST" });
      setEvents((prev) =>
        (prev ?? []).map((e) => (e.id === id ? { ...e, acknowledged_at: new Date().toISOString(), acknowledged_by: user?.username ?? "" } : e)),
      );
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };

  const ackAll = async () => {
    try {
      const res = await api<{ count: number }>("/api/events/ack-all", { method: "POST" });
      toast(t("Potvrzeno {count} událostí.", { count: res.count }));
      void load();
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };

  if (!dashboard || !events) return error ? <Alert>{error}</Alert> : <PageLoader />;

  return (
    <div className="page">
      <PageHeader
        title={t("Monitoring")}
        subtitle={t("Sledováno {monitored_total} kamer na {nvr_total} zařízeních", { monitored_total: dashboard.monitored_total, nvr_total: dashboard.nvr_total })}
        actions={
          canAck && dashboard.unacknowledged_events > 0 ? (
            <button type="button" className="btn btn-ghost" onClick={() => void ackAll()}>
              <CheckCheck size={16} /> {t("Potvrdit vše (")}{dashboard.unacknowledged_events})
            </button>
          ) : null
        }
      />
      {error && <Alert>{error}</Alert>}

      <section className="panel">
        <div className="panel-header">
          <h2>{t("Aktuální problémy")}</h2>
        </div>
        {dashboard.problems.length === 0 ? (
          <div className="all-good">
            <CircleCheck size={22} />
            <div>
              <strong>{t("Bez problémů")}</strong>
              <span>{t("Všechna zařízení a sledované kamery fungují.")}</span>
            </div>
          </div>
        ) : (
          <ul className="problem-list">
            {dashboard.problems.map((p, i) => (
              <li key={`${p.kind}-${p.nvr_id}-${p.camera_id ?? i}`} className={`problem problem-${p.severity}`}>
                <div className="problem-text">
                  <Link to={`/devices/${p.nvr_id}`}>
                    <strong>{p.title}</strong>
                  </Link>
                  <span>{p.message}</span>
                </div>
                {p.since && <span className="problem-since">{t("od")} {formatDateTime(p.since)}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <div className="panel-header wrap">
          <h2>{t("Historie událostí")}</h2>
          <div className="filters">
            <select className="input input-small" value={severity} onChange={(e) => setSeverity(e.target.value as Severity | "")} aria-label={t("Závažnost")}>
              <option value="">{t("Všechny závažnosti")}</option>
              <option value="critical">{t("Kritické")}</option>
              <option value="warning">{t("Varování")}</option>
              <option value="info">{t("Informační")}</option>
            </select>
            <label className="check">
              <input type="checkbox" checked={unackedOnly} onChange={(e) => setUnackedOnly(e.target.checked)} />
              <span>{t("Jen nepotvrzené")}</span>
            </label>
          </div>
        </div>
        {events.length === 0 ? (
          <p className="muted">{t("Žádné události.")}</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("Čas")}</th>
                  <th>{t("Závažnost")}</th>
                  <th>{t("Zařízení")}</th>
                  <th>{t("Popis")}</th>
                  <th className="right">{t("Stav")}</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} className={!e.acknowledged_at && e.severity !== "info" ? "row-highlight" : ""}>
                    <td className="nowrap" title={formatDateTime(e.ts)}>
                      {formatDateTime(e.ts)}
                      <div className="muted small">{formatRelative(e.ts)}</div>
                    </td>
                    <td>
                      <SeverityPill severity={e.severity} />
                    </td>
                    <td>{e.nvr_id ? <Link to={`/devices/${e.nvr_id}`}>{e.nvr_name || `#${e.nvr_id}`}</Link> : "—"}</td>
                    <td>{e.message}</td>
                    <td className="right nowrap">
                      {e.severity === "info" ? null : e.acknowledged_at ? (
                        <span className="muted small" title={formatDateTime(e.acknowledged_at)}>
                          <Check size={14} /> {e.acknowledged_by}
                        </span>
                      ) : canAck ? (
                        <button type="button" className="btn btn-ghost btn-small" onClick={() => void ack(e.id)}>
                          {t("Potvrdit")}
                        </button>
                      ) : (
                        <span className="muted small">{t("Nepotvrzeno")}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {hasMore && (
          <div className="center">
            <button type="button" className="btn btn-ghost" onClick={() => void loadMore()} disabled={loadingMore}>
              {loadingMore ? <Spinner size={16} /> : null} {t("Načíst starší")}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
