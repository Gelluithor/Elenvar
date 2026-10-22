import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Download, Film, Pause, Play, RotateCcw, RotateCw, Search } from "lucide-react";
import { StreamPlayer } from "../components/StreamPlayer";
import { Alert, EmptyState, PageHeader, PageLoader, Spinner, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { formatClock, formatDuration, parseDeviceTime, RECORD_TYPE_LABELS, todayIso, toDeviceTime } from "../lib/format";
import type { Camera, Segment } from "../types";
import { t } from "../lib/i18n";

const DAY_MS = 24 * 3600 * 1000;

function dayStart(date: string): Date {
  return parseDeviceTime(`${date}T00:00:00`);
}

function shiftDate(date: string, days: number): string {
  const d = dayStart(date);
  d.setDate(d.getDate() + days);
  return toDeviceTime(d).slice(0, 10);
}

export function PlaybackPage() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const [cameras, setCameras] = useState<Camera[] | null>(null);
  const [cameraId, setCameraId] = useState<number | null>(() => Number(params.get("camera")) || null);
  const [date, setDate] = useState<string>(() => todayIso());
  const [segments, setSegments] = useState<Segment[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playStart, setPlayStart] = useState<string | null>(null);
  const [position, setPosition] = useState<Date | null>(null);
  const [hover, setHover] = useState<{ x: number; label: string } | null>(null);
  const baseTime = useRef<number | null>(null);

  useEffect(() => {
    api<Camera[]>("/api/cameras")
      .then(setCameras)
      .catch((err) => setError(errorMessage(err)));
  }, []);

  const search = useCallback(async () => {
    if (!cameraId) return;
    setLoading(true);
    setError(null);
    setSegments(null);
    try {
      const res = await api<{ segments: Segment[] }>(`/api/playback/${cameraId}/recordings?date=${date}`);
      setSegments(res.segments);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [cameraId, date]);

  useEffect(() => {
    setPlayStart(null);
    setPosition(null);
    if (cameraId) void search();
  }, [cameraId, date, search]);

  useEffect(() => {
    if (cameraId) {
      if (params.get("camera") !== String(cameraId)) setParams({ camera: String(cameraId) }, { replace: true });
    }
  }, [cameraId, params, setParams]);

  const groups = useMemo(() => {
    // Seskupení podle ID zařízení – dvě NVR mohou mít stejný název.
    const map = new Map<number, Camera[]>();
    for (const cam of cameras ?? []) {
      const list = map.get(cam.nvr_id) ?? [];
      list.push(cam);
      map.set(cam.nvr_id, list);
    }
    return [...map.values()];
  }, [cameras]);

  const day0 = dayStart(date).getTime();
  const parsed = useMemo(
    () => (segments ?? []).map((s) => ({ ...s, startMs: parseDeviceTime(s.start).getTime(), endMs: parseDeviceTime(s.end).getTime() })),
    [segments],
  );

  const startAt = (when: Date) => {
    const time = when.getTime();
    const target = parsed.find((s) => s.endMs > time);
    if (!target) {
      toast(t("Po zvoleném čase už není žádný záznam."), "info");
      return;
    }
    const begin = new Date(Math.max(time, target.startMs));
    baseTime.current = null;
    setPosition(begin);
    setPlayStart(toDeviceTime(begin));
  };

  const onTimelineClick = (event: MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    startAt(new Date(day0 + fraction * DAY_MS));
  };

  const onTimelineMove = (event: MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    setHover({ x: fraction * 100, label: formatClock(new Date(day0 + fraction * DAY_MS)) });
  };

  const onTime = useCallback(
    (seconds: number) => {
      if (!playStart) return;
      if (baseTime.current === null) baseTime.current = seconds;
      const begin = parseDeviceTime(playStart).getTime();
      setPosition(new Date(begin + (seconds - baseTime.current) * 1000));
    },
    [playStart],
  );

  const pause = () => setPlayStart(null);
  const resume = () => position && startAt(position);
  const skip = (seconds: number) => {
    const from = position ?? (parsed[0] ? new Date(parsed[0].startMs) : null);
    if (from) startAt(new Date(from.getTime() + seconds * 1000));
  };

  if (!cameras) return error ? <Alert>{error}</Alert> : <PageLoader />;
  const camera = cameras.find((c) => c.id === cameraId) ?? null;
  const totalRecorded = parsed.reduce((sum, s) => sum + (s.endMs - s.startMs) / 1000, 0);

  return (
    <div className="page">
      <PageHeader title={t("Záznamy")} subtitle={t("Vyhledání a přehrání záznamů z NVR. Časy odpovídají času zařízení.")} />

      <div className="panel playback-controls">
        <div className="field">
          <label htmlFor="pb-camera">{t("Kamera")}</label>
          <select id="pb-camera" className="input" value={cameraId ?? ""} onChange={(e) => setCameraId(Number(e.target.value) || null)}>
            <option value="">{t("— vyberte kameru —")}</option>
            {groups.map((list) => (
              <optgroup key={list[0].nvr_id} label={list[0].nvr_name}>
                {list.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.channel}. {c.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="pb-date">{t("Datum")}</label>
          <div className="date-nav">
            <button type="button" className="icon-btn" onClick={() => setDate((d) => shiftDate(d, -1))} aria-label={t("Předchozí den")}>
              <ChevronLeft size={18} />
            </button>
            <input id="pb-date" type="date" className="input" value={date} max={todayIso()} onChange={(e) => e.target.value && setDate(e.target.value)} />
            <button type="button" className="icon-btn" onClick={() => setDate((d) => shiftDate(d, 1))} aria-label={t("Další den")} disabled={date >= todayIso()}>
              <ChevronRight size={18} />
            </button>
          </div>
        </div>
        <button type="button" className="btn btn-ghost" onClick={() => void search()} disabled={!cameraId || loading}>
          {loading ? <Spinner size={16} /> : <Search size={16} />} {t("Hledat")}
        </button>
      </div>

      {error && <Alert>{error}</Alert>}

      {!cameraId ? (
        <EmptyState icon={<Film size={28} />} title={t("Vyberte kameru")}>
          {t("Po výběru kamery a data se zobrazí časová osa se záznamy.")}
        </EmptyState>
      ) : (
        <>
          <div className="panel">
            <div className="playback-player">
              {playStart ? (
                <StreamPlayer key={playStart} path={`/api/playback/${cameraId}/stream?start=${encodeURIComponent(playStart)}`} live={false} onTime={onTime} />
              ) : (
                <div className="player player-idle">
                  <Film size={30} />
                  <span>{segments && segments.length ? t("Klikněte na časovou osu pro přehrání") : t("Žádný vybraný záznam")}</span>
                </div>
              )}
            </div>
            <div className="playback-bar">
              <button type="button" className="icon-btn" onClick={() => skip(-30)} title={t("Zpět o 30 s")} disabled={!parsed.length}>
                <RotateCcw size={18} />
              </button>
              {playStart ? (
                <button type="button" className="icon-btn icon-btn-lg" onClick={pause} title={t("Pozastavit")}>
                  <Pause size={20} />
                </button>
              ) : (
                <button type="button" className="icon-btn icon-btn-lg" onClick={resume} title={t("Přehrát")} disabled={!position}>
                  <Play size={20} />
                </button>
              )}
              <button type="button" className="icon-btn" onClick={() => skip(30)} title={t("Vpřed o 30 s")} disabled={!parsed.length}>
                <RotateCw size={18} />
              </button>
              <span className="playback-time">{position ? `${formatClock(position)}` : "--:--:--"}</span>
              <span className="toolbar-spacer" />
              <span className="muted small">
                {camera ? `${camera.nvr_name} · ${camera.name}` : ""}
              </span>
            </div>

            <div className="timeline-wrap">
              <div className="timeline" onClick={onTimelineClick} onMouseMove={onTimelineMove} onMouseLeave={() => setHover(null)} role="presentation">
                {parsed.map((s) => {
                  const left = ((s.startMs - day0) / DAY_MS) * 100;
                  const width = Math.max(0.15, ((s.endMs - s.startMs) / DAY_MS) * 100);
                  return (
                    <span
                      key={`${s.start}-${s.end}`}
                      className={`timeline-seg seg-${s.type.toLowerCase() === "timing" ? "timing" : "event"}`}
                      style={{ left: `${Math.max(0, left)}%`, width: `${width}%` }}
                    />
                  );
                })}
                {position && position.getTime() >= day0 && position.getTime() <= day0 + DAY_MS && (
                  <span className="timeline-cursor" style={{ left: `${((position.getTime() - day0) / DAY_MS) * 100}%` }} />
                )}
                {hover && (
                  <span className="timeline-hover" style={{ left: `${hover.x}%` }}>
                    {hover.label}
                  </span>
                )}
              </div>
              <div className="timeline-ticks" aria-hidden>
                {Array.from({ length: 9 }, (_, i) => (
                  <span key={i} style={{ left: `${(i * 3 * 100) / 24}%` }}>
                    {String(i * 3).padStart(2, "0")}:00
                  </span>
                ))}
              </div>
              <div className="timeline-legend">
                <span>
                  <i className="seg-timing" /> {t("Průběžný záznam")}
                </span>
                <span>
                  <i className="seg-event" /> {t("Událost / pohyb")}
                </span>
                {segments && <span className="muted">{t("Celkem")} {formatDuration(totalRecorded)} {t("záznamu")}</span>}
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h2>{t("Nalezené záznamy")}</h2>
              {segments && <span className="muted small">{segments.length} {t("úseků")}</span>}
            </div>
            {loading && <Spinner label={t("Vyhledávám záznamy…")} />}
            {segments && segments.length === 0 && <p className="muted">{t("Pro tento den nebyly nalezeny žádné záznamy.")}</p>}
            {segments && segments.length > 0 && (
              <div className="table-wrap table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("Začátek")}</th>
                      <th>{t("Konec")}</th>
                      <th>{t("Délka")}</th>
                      <th>{t("Typ")}</th>
                      <th className="right">{t("Akce")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {parsed.map((s) => (
                      <tr key={`${s.start}-${s.end}`}>
                        <td>{formatClock(new Date(s.startMs))}</td>
                        <td>{formatClock(new Date(s.endMs))}</td>
                        <td>{formatDuration((s.endMs - s.startMs) / 1000)}</td>
                        <td>{RECORD_TYPE_LABELS[s.type] ? t(RECORD_TYPE_LABELS[s.type]) : s.type || "—"}</td>
                        <td className="right nowrap">
                          <button type="button" className="btn btn-ghost btn-small" onClick={() => startAt(new Date(s.startMs))}>
                            <Play size={14} /> {t("Přehrát")}
                          </button>
                          <a
                            className="btn btn-ghost btn-small"
                            href={`/api/playback/${cameraId}/download?start=${encodeURIComponent(s.start)}&end=${encodeURIComponent(s.end)}`}
                            download
                          >
                            <Download size={14} /> {t("Stáhnout")}
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
