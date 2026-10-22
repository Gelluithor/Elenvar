import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Film, ImageOff, Pencil, Power, RefreshCw, SlidersHorizontal, Trash2, Video } from "lucide-react";
import { useAuth } from "../auth";
import {
  Alert,
  CameraStatePill,
  ConfirmDialog,
  Modal,
  NvrStatusPill,
  PageHeader,
  PageLoader,
  Segmented,
  Spinner,
  Switch,
  usePolling,
  useToast,
} from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { formatBytesMb, formatDateTime, formatRelative, hasRole } from "../lib/format";
import type { Camera, Nvr, StreamSettings } from "../types";
import { NvrFormModal } from "./Devices";

const HEALTHY = new Set(["ok", "idle", "standby", "sleeping", "sleep"]);

function Snapshot({ camera, refreshKey }: { camera: Camera; refreshKey: number }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [refreshKey]);
  if (camera.state !== "online" || failed) {
    return (
      <div className="thumb thumb-empty">
        <ImageOff size={18} />
      </div>
    );
  }
  return (
    <img
      className="thumb"
      src={`/api/cameras/${camera.id}/snapshot?t=${refreshKey}`}
      alt={`Náhled ${camera.name}`}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

function fpsLabel(value: string | number): string {
  const n = Number(value);
  if (n === 0) return "Plná snímková frekvence";
  return `${(n / 100).toLocaleString("cs-CZ")} fps`;
}

function StreamSettingsModal({ nvrId, camera, onClose }: { nvrId: number; camera: Camera; onClose: () => void }) {
  const toast = useToast();
  const [kind, setKind] = useState<"main" | "sub">("sub");
  const [data, setData] = useState<StreamSettings | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api<StreamSettings>(`/api/nvrs/${nvrId}/channels/${camera.channel}/stream/${kind}`)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setForm(Object.fromEntries(Object.entries(d.current).map(([k, v]) => [k, String(v)])));
      })
      .catch((err) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [nvrId, camera.channel, kind]);

  const set = (key: string, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!data) return;
    const changes: Record<string, string | number> = {};
    for (const [key, value] of Object.entries(form)) {
      if (String(data.current[key]) !== value) {
        changes[key] = typeof data.current[key] === "number" ? Number(value) : value;
      }
    }
    if ("videoResolutionWidth" in changes || "videoResolutionHeight" in changes) {
      changes.videoResolutionWidth = Number(form.videoResolutionWidth);
      changes.videoResolutionHeight = Number(form.videoResolutionHeight);
    }
    if (Object.keys(changes).length === 0) {
      onClose();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await api<StreamSettings>(`/api/nvrs/${nvrId}/channels/${camera.channel}/stream/${kind}`, {
        method: "PUT",
        body: changes,
      });
      setData(updated);
      toast("Nastavení streamu bylo uloženo.");
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const options = data?.options ?? {};
  const has = (key: string) => data !== null && key in data.current;
  const resolutionValue = `${form.videoResolutionWidth}x${form.videoResolutionHeight}`;
  const resolutions = data?.resolutions ?? [];

  return (
    <Modal
      title={`Stream – ${camera.name}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Zrušit
          </button>
          <button type="submit" form="stream-form" className="btn btn-primary" disabled={busy || !data}>
            {busy ? <Spinner size={16} /> : null} Uložit do kamery
          </button>
        </>
      }
    >
      <Segmented<"main" | "sub">
        full
        label="Stream"
        value={kind}
        onChange={setKind}
        options={[
          { value: "sub", label: "Substream (náhledy)" },
          { value: "main", label: "Hlavní stream (záznam)" },
        ]}
      />
      {!data && !error && <Spinner label="Načítám nastavení z kamery…" />}
      {error && <Alert>{error}</Alert>}
      {data && (
        <form id="stream-form" className="form" onSubmit={submit}>
          {has("videoCodecType") && (
            <div className="field">
              <label htmlFor="st-codec">Kodek</label>
              <select id="st-codec" className="input" value={form.videoCodecType} onChange={(e) => set("videoCodecType", e.target.value)}>
                {(options.videoCodecType ?? [form.videoCodecType]).map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
              <div className="field-hint">Pro přehrávání ve všech prohlížečích doporučujeme H.264 (alespoň u substreamu).</div>
            </div>
          )}
          {has("videoResolutionWidth") && has("videoResolutionHeight") && (
            <div className="field">
              <label htmlFor="st-res">Rozlišení</label>
              <select
                id="st-res"
                className="input"
                value={resolutionValue}
                onChange={(e) => {
                  const [w, h] = e.target.value.split("x");
                  setForm((f) => ({ ...f, videoResolutionWidth: w, videoResolutionHeight: h }));
                }}
              >
                {!resolutions.some(([w, h]) => `${w}x${h}` === resolutionValue) && <option value={resolutionValue}>{resolutionValue.replace("x", " × ")}</option>}
                {resolutions.map(([w, h]) => (
                  <option key={`${w}x${h}`} value={`${w}x${h}`}>
                    {w} × {h}
                  </option>
                ))}
              </select>
            </div>
          )}
          {has("maxFrameRate") && (
            <div className="field">
              <label htmlFor="st-fps">Snímková frekvence</label>
              <select id="st-fps" className="input" value={form.maxFrameRate} onChange={(e) => set("maxFrameRate", e.target.value)}>
                {!(options.maxFrameRate ?? []).includes(form.maxFrameRate) && <option value={form.maxFrameRate}>{fpsLabel(form.maxFrameRate)}</option>}
                {(options.maxFrameRate ?? []).map((o) => (
                  <option key={o} value={o}>
                    {fpsLabel(o)}
                  </option>
                ))}
              </select>
            </div>
          )}
          {has("videoQualityControlType") && (
            <div className="field">
              <label htmlFor="st-rc">Řízení datového toku</label>
              <select id="st-rc" className="input" value={form.videoQualityControlType} onChange={(e) => set("videoQualityControlType", e.target.value)}>
                {(options.videoQualityControlType ?? [form.videoQualityControlType]).map((o) => (
                  <option key={o} value={o}>
                    {o === "CBR" ? "Konstantní (CBR)" : o === "VBR" ? "Proměnný (VBR)" : o}
                  </option>
                ))}
              </select>
            </div>
          )}
          {form.videoQualityControlType === "CBR" && has("constantBitRate") && (
            <div className="field">
              <label htmlFor="st-cbr">Datový tok (kb/s)</label>
              <input id="st-cbr" className="input" type="number" min={data.ranges.constantBitRate?.[0] ?? 16} max={data.ranges.constantBitRate?.[1] ?? 100000} value={form.constantBitRate} onChange={(e) => set("constantBitRate", e.target.value)} />
            </div>
          )}
          {form.videoQualityControlType !== "CBR" && has("vbrUpperCap") && (
            <div className="field">
              <label htmlFor="st-vbr">Maximální datový tok (kb/s)</label>
              <input id="st-vbr" className="input" type="number" min={data.ranges.vbrUpperCap?.[0] ?? 16} max={data.ranges.vbrUpperCap?.[1] ?? 100000} value={form.vbrUpperCap} onChange={(e) => set("vbrUpperCap", e.target.value)} />
            </div>
          )}
          {has("GovLength") && (
            <div className="field">
              <label htmlFor="st-gop">Interval I-snímků</label>
              <input id="st-gop" className="input" type="number" min={data.ranges.GovLength?.[0] ?? 1} max={data.ranges.GovLength?.[1] ?? 1000} value={form.GovLength} onChange={(e) => set("GovLength", e.target.value)} />
            </div>
          )}
          <Alert kind="warning">Změna se zapíše přímo do kamery a krátce přeruší její stream i záznam.</Alert>
        </form>
      )}
    </Modal>
  );
}

export function DeviceDetailPage() {
  const { id } = useParams();
  const nvrId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();
  const { user } = useAuth();
  const isAdmin = hasRole(user?.role, "admin");
  const canPlayback = hasRole(user?.role, "operator");
  const [nvr, setNvr] = useState<Nvr | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState<"reboot" | "delete" | null>(null);
  const [streamCamera, setStreamCamera] = useState<Camera | null>(null);
  const [snapKey, setSnapKey] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      setNvr(await api<Nvr>(`/api/nvrs/${nvrId}`));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [nvrId]);

  useEffect(() => {
    void load();
  }, [load]);
  usePolling(() => void load(), 15000);
  usePolling(() => setSnapKey(Date.now()), 60000);

  const pollNow = async () => {
    setPolling(true);
    try {
      setNvr({ ...(await api<Nvr>(`/api/nvrs/${nvrId}/poll`, { method: "POST" })), cameras: nvr?.cameras });
      await load();
      setSnapKey(Date.now());
      toast("Stav zařízení byl aktualizován.");
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setPolling(false);
    }
  };

  const toggleMonitored = async (camera: Camera, monitored: boolean) => {
    try {
      const updated = await api<Camera>(`/api/cameras/${camera.id}`, { method: "PATCH", body: { monitored } });
      setNvr((n) => (n ? { ...n, cameras: n.cameras?.map((c) => (c.id === updated.id ? updated : c)) } : n));
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };

  if (!nvr) return error ? <Alert>{error}</Alert> : <PageLoader />;
  const cameras = nvr.cameras ?? [];

  return (
    <div className="page">
      <Link to="/devices" className="back-link">
        <ArrowLeft size={16} /> Zařízení
      </Link>
      <PageHeader
        title={nvr.name}
        subtitle={
          <span className="inline-flex">
            <NvrStatusPill status={nvr.status} />
            {nvr.model && <span>{nvr.model}</span>}
          </span>
        }
        actions={
          isAdmin && (
            <>
              <button type="button" className="btn btn-ghost" onClick={() => void pollNow()} disabled={polling}>
                {polling ? <Spinner size={16} /> : <RefreshCw size={16} />} Zkontrolovat nyní
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => setEditing(true)}>
                <Pencil size={16} /> Upravit
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => setConfirm("reboot")} disabled={nvr.status !== "online"}>
                <Power size={16} /> Restartovat
              </button>
              <button type="button" className="btn btn-ghost btn-danger-text" onClick={() => setConfirm("delete")}>
                <Trash2 size={16} /> Smazat
              </button>
            </>
          )
        }
      />
      {error && <Alert>{error}</Alert>}
      {nvr.status === "auth_error" && (
        <Alert>
          {nvr.status_message} {isAdmin ? "Opravte údaje přes „Upravit“ nebo po opravě na NVR klikněte na „Zkontrolovat nyní“." : ""}
        </Alert>
      )}
      {(nvr.status === "offline" || nvr.status === "error") && <Alert>{nvr.status_message || "Zařízení je nedostupné."}</Alert>}

      <div className="detail-grid">
        <section className="panel">
          <h2>Informace</h2>
          <dl className="info-list">
            <dt>Typ</dt>
            <dd>{nvr.device_type || "—"}</dd>
            <dt>Sériové číslo</dt>
            <dd className="mono small">{nvr.serial_number || "—"}</dd>
            <dt>Firmware</dt>
            <dd>{nvr.firmware || "—"}</dd>
            {isAdmin && (
              <>
                <dt>Adresa</dt>
                <dd className="mono small">
                  {nvr.use_https ? "https" : "http"}://{nvr.host}:{nvr.http_port} · RTSP {nvr.rtsp_port}
                </dd>
                <dt>MAC</dt>
                <dd className="mono small">{nvr.mac_address || "—"}</dd>
              </>
            )}
            <dt>Čas zařízení</dt>
            <dd>
              {nvr.device_time ? formatDateTime(nvr.device_time) : "—"}
              {nvr.time_drift_sec !== null && Math.abs(nvr.time_drift_sec) > 5 && (
                <span className={Math.abs(nvr.time_drift_sec) > 120 ? "tone-bad-text" : "muted"}> (odchylka {nvr.time_drift_sec} s)</span>
              )}
            </dd>
            <dt>Naposledy dostupné</dt>
            <dd>{formatRelative(nvr.last_seen_at)}</dd>
            <dt>Poslední kontrola</dt>
            <dd>{formatRelative(nvr.last_poll_at)}</dd>
            {nvr.transcode && (
              <>
                <dt>Video</dt>
                <dd>Převod na H.264 zapnut</dd>
              </>
            )}
            {isAdmin && nvr.notes && (
              <>
                <dt>Poznámka</dt>
                <dd className="prewrap">{nvr.notes}</dd>
              </>
            )}
          </dl>
        </section>

        <section className="panel">
          <h2>Úložiště</h2>
          {nvr.disk_problems.length > 0 && (
            <Alert>
              {nvr.disk_problems.map((p) => (
                <div key={p}>{p}</div>
              ))}
            </Alert>
          )}
          {nvr.disks.length === 0 ? (
            <p className="muted">Žádné disky nebyly nalezeny.</p>
          ) : (
            <ul className="disk-list">
              {nvr.disks.map((d) => {
                const used = d.capacity_mb > 0 ? Math.round(((d.capacity_mb - d.free_mb) / d.capacity_mb) * 100) : 0;
                const healthy = HEALTHY.has(d.status.toLowerCase());
                return (
                  <li key={`${d.kind}-${d.id}`}>
                    <div className="disk-head">
                      <strong>
                        {d.kind} {d.name}
                      </strong>
                      <span className={`pill ${healthy ? "pill-ok" : "pill-bad"}`}>{d.status || "?"}</span>
                    </div>
                    <div className="progress" aria-label={`Obsazeno ${used} %`}>
                      <span style={{ width: `${used}%` }} />
                    </div>
                    <div className="muted small">
                      {formatBytesMb(d.capacity_mb)} celkem · {formatBytesMb(d.free_mb)} volno
                      {d.free_mb === 0 && healthy ? " (přepisování nejstarších záznamů)" : ""}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <h2>Kamery ({cameras.length})</h2>
          <span className="muted small">Sledované kamery vyvolají upozornění, když přestanou fungovat.</span>
        </div>
        {cameras.length === 0 ? (
          <p className="muted">Zařízení zatím nehlásí žádné kamery.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Náhled</th>
                  <th>Kamera</th>
                  <th>Stav</th>
                  <th>Sledovat</th>
                  <th className="right">Akce</th>
                </tr>
              </thead>
              <tbody>
                {cameras.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Snapshot camera={c} refreshKey={snapKey} />
                    </td>
                    <td>
                      <strong>{c.name}</strong>
                      <div className="muted small">
                        Kanál {c.channel}
                        {c.ip_address ? ` · ${c.ip_address}` : ""}
                      </div>
                    </td>
                    <td>
                      <CameraStatePill state={c.state} />
                      {c.detail && c.state !== "online" && <div className="muted small">{c.detail}</div>}
                      {c.status_changed_at && <div className="muted small">od {formatDateTime(c.status_changed_at)}</div>}
                    </td>
                    <td>
                      <Switch checked={c.monitored} onChange={(v) => void toggleMonitored(c, v)} label={<span className="sr-only">Sledovat {c.name}</span>} disabled={!isAdmin} />
                    </td>
                    <td className="right nowrap">
                      <Link className="btn btn-ghost btn-small" to={`/live?camera=${c.id}`}>
                        <Video size={14} /> Živě
                      </Link>
                      {canPlayback && (
                        <Link className="btn btn-ghost btn-small" to={`/playback?camera=${c.id}`}>
                          <Film size={14} /> Záznamy
                        </Link>
                      )}
                      {isAdmin && (
                        <button type="button" className="btn btn-ghost btn-small" onClick={() => setStreamCamera(c)} disabled={nvr.status !== "online"}>
                          <SlidersHorizontal size={14} /> Stream
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {editing && (
        <NvrFormModal
          nvr={nvr}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            toast("Zařízení bylo uloženo.");
            void load();
            window.setTimeout(() => void load(), 4000);
          }}
        />
      )}
      {confirm === "reboot" && (
        <ConfirmDialog
          title="Restartovat zařízení?"
          message={`Zařízení ${nvr.name} se restartuje. Po dobu restartu (obvykle 2–5 minut) nebude nahrávat ani dostupné.`}
          confirmLabel="Restartovat"
          danger
          onClose={() => setConfirm(null)}
          onConfirm={async () => {
            await api(`/api/nvrs/${nvrId}/reboot`, { method: "POST" });
            toast("Příkaz k restartu byl odeslán.");
          }}
        />
      )}
      {confirm === "delete" && (
        <ConfirmDialog
          title="Smazat zařízení?"
          message={`Zařízení ${nvr.name} a jeho kamery budou odebrány z Elenvar. Záznamy na NVR zůstanou zachovány.`}
          confirmLabel="Smazat"
          danger
          onClose={() => setConfirm(null)}
          onConfirm={async () => {
            await api(`/api/nvrs/${nvrId}`, { method: "DELETE" });
            toast("Zařízení bylo smazáno.");
            navigate("/devices");
          }}
        />
      )}
      {streamCamera && <StreamSettingsModal nvrId={nvrId} camera={streamCamera} onClose={() => setStreamCamera(null)} />}
    </div>
  );
}
