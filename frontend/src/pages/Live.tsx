import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Eraser, Expand, Grid2x2, Grid3x3, LayoutGrid, Maximize2, Minimize2, Plus, Search, Square, VideoOff, X } from "lucide-react";
import { useAuth } from "../auth";
import { StreamPlayer } from "../components/StreamPlayer";
import { Alert, EmptyState, PageLoader, Segmented, StatusDot, usePolling } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import type { Camera } from "../types";
import { t } from "../lib/i18n";

type Quality = "auto" | "main" | "sub";
const LAYOUTS = [1, 4, 9, 16] as const;
type LayoutSize = (typeof LAYOUTS)[number];

interface SavedState {
  layout: LayoutSize;
  slots: (number | null)[];
  quality: Quality;
}

function storageKey(username: string) {
  return `elenvar.live.${username}`;
}

function loadState(username: string): SavedState {
  try {
    const raw = window.localStorage.getItem(storageKey(username));
    if (raw) {
      const parsed = JSON.parse(raw) as SavedState;
      if (LAYOUTS.includes(parsed.layout) && Array.isArray(parsed.slots)) {
        return {
          layout: parsed.layout,
          slots: parsed.slots.slice(0, 16).map((v) => (typeof v === "number" ? v : null)),
          quality: parsed.quality === "main" || parsed.quality === "sub" ? parsed.quality : "auto",
        };
      }
    }
  } catch {
    /* poškozený nebo nedostupný localStorage */
  }
  return { layout: 4, slots: [], quality: "auto" };
}

const LAYOUT_ICON: Record<LayoutSize, ReactNode> = {
  1: <Square size={16} />,
  4: <Grid2x2 size={16} />,
  9: <Grid3x3 size={16} />,
  16: <LayoutGrid size={16} />,
};

export function LivePage() {
  const { user } = useAuth();
  const username = user?.username ?? "";
  const [cameras, setCameras] = useState<Camera[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<SavedState>(() => loadState(username));
  const [selected, setSelected] = useState<number | null>(null);
  const [maximized, setMaximized] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const [params, setParams] = useSearchParams();
  const tileRefs = useRef<(HTMLDivElement | null)[]>([]);

  const loadCameras = useCallback(async () => {
    try {
      setCameras(await api<Camera[]>("/api/cameras"));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void loadCameras();
  }, [loadCameras]);
  usePolling(() => void loadCameras(), 30000);

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey(username), JSON.stringify(state));
    } catch {
      /* ignorovat */
    }
  }, [state, username]);

  // Odkaz "Živě" z detailu zařízení: ?camera=ID otevře kameru samostatně.
  useEffect(() => {
    const id = Number(params.get("camera"));
    if (id > 0) {
      setState((s) => {
        const slots = [...s.slots];
        slots[0] = id;
        return { ...s, layout: 1, slots };
      });
      setMaximized(null);
      params.delete("camera");
      setParams(params, { replace: true });
    }
  }, [params, setParams]);

  const byId = useMemo(() => new Map((cameras ?? []).map((c) => [c.id, c])), [cameras]);

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    // Seskupení podle ID zařízení – dvě NVR mohou mít stejný název.
    const map = new Map<number, Camera[]>();
    for (const cam of cameras ?? []) {
      if (q && !`${cam.name} ${cam.nvr_name}`.toLowerCase().includes(q)) continue;
      const list = map.get(cam.nvr_id) ?? [];
      list.push(cam);
      map.set(cam.nvr_id, list);
    }
    return [...map.values()];
  }, [cameras, filter]);

  const setLayout = (layout: LayoutSize) => {
    setState((s) => ({ ...s, layout }));
    setMaximized(null);
    if (selected !== null && selected >= layout) setSelected(null);
  };

  const assign = (cameraId: number, slot?: number) => {
    setState((s) => {
      const slots = [...s.slots];
      while (slots.length < s.layout) slots.push(null);
      let target = slot ?? selected ?? -1;
      if (target < 0 || target >= s.layout) {
        target = slots.slice(0, s.layout).findIndex((v) => v === null);
        if (target < 0) target = 0;
      }
      const existing = slots.indexOf(cameraId);
      if (existing >= 0 && existing !== target) slots[existing] = slots[target] ?? null;
      slots[target] = cameraId;
      return { ...s, slots };
    });
    setSelected(null);
  };

  const clearSlot = (slot: number) => {
    setState((s) => {
      const slots = [...s.slots];
      slots[slot] = null;
      return { ...s, slots };
    });
    if (maximized === slot) setMaximized(null);
  };

  const fullscreen = (slot: number) => {
    const el = tileRefs.current[slot];
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.().catch(() => undefined);
  };

  if (!cameras) return error ? <Alert>{error}</Alert> : <PageLoader />;

  const visibleSlots = maximized !== null ? [maximized] : Array.from({ length: state.layout }, (_, i) => i);
  const columns = maximized !== null ? 1 : Math.sqrt(state.layout);
  const qualityFor = (count: number): "main" | "sub" =>
    state.quality === "auto" ? (count === 1 ? "main" : "sub") : state.quality;
  const quality = qualityFor(visibleSlots.length);

  return (
    <div className="live-page">
      <aside className="live-sidebar">
        <div className="search">
          <Search size={16} aria-hidden />
          <input className="input" placeholder={t("Hledat kameru…")} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={t("Hledat kameru")} />
        </div>
        <div className="camera-list">
          {groups.length === 0 && <p className="muted small">{t("Žádné kamery.")}</p>}
          {groups.map((list) => (
            <div key={list[0].nvr_id} className="camera-group">
              <div className="camera-group-title">{list[0].nvr_name}</div>
              {list.map((cam) => (
                <button
                  key={cam.id}
                  type="button"
                  className="camera-item"
                  draggable
                  onDragStart={(e) => e.dataTransfer.setData("text/x-elenvar-camera", String(cam.id))}
                  onClick={() => assign(cam.id)}
                  title={t("Kliknutím přidáte do vybraného nebo prvního volného okna, případně přetáhněte")}
                >
                  <StatusDot state={cam.state} />
                  <span className="camera-item-name">{cam.name}</span>
                  <span className="camera-item-ch">{cam.channel}</span>
                  <Plus size={14} className="camera-item-add" />
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>

      <section className="live-main">
        <div className="live-toolbar">
          <Segmented
            label={t("Rozložení")}
            value={maximized === null ? state.layout : null}
            onChange={(l) => setLayout(l)}
            options={LAYOUTS.map((l) => ({
              value: l,
              title: l === 1 ? t("1 okno") : l === 4 ? t("{count} okna", { count: l }) : t("{count} oken", { count: l }),
              label: (
                <>
                  {LAYOUT_ICON[l]}
                  <span>{l}</span>
                </>
              ),
            }))}
          />
          <Segmented<Quality>
            label={t("Kvalita")}
            value={state.quality}
            onChange={(q) => setState((s) => ({ ...s, quality: q }))}
            options={[
              { value: "auto", label: t("Auto") },
              { value: "sub", label: t("Nízká") },
              { value: "main", label: t("Vysoká") },
            ]}
          />
          <span className="toolbar-spacer" />
          <button type="button" className="btn btn-ghost btn-small" onClick={() => setState((s) => ({ ...s, slots: [] }))}>
            <Eraser size={15} /> {t("Vyprázdnit")}
          </button>
        </div>

        {cameras.length === 0 ? (
          <EmptyState icon={<VideoOff size={28} />} title={t("Žádné kamery")}>
            {t("Kamery se zobrazí po přidání a prvním načtení zařízení.")}
          </EmptyState>
        ) : (
          <div className="video-grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
            {visibleSlots.map((slot) => {
              const cam = state.slots[slot] != null ? byId.get(state.slots[slot] as number) : undefined;
              return (
                <div
                  key={slot}
                  ref={(el) => { tileRefs.current[slot] = el; }}
                  className={`tile${selected === slot ? " selected" : ""}`}
                  onClick={() => !cam && setSelected(slot === selected ? null : slot)}
                  onDoubleClick={() => cam && setMaximized(maximized === slot ? null : slot)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    const id = Number(e.dataTransfer.getData("text/x-elenvar-camera"));
                    if (id > 0) assign(id, slot);
                  }}
                >
                  {cam ? (
                    <>
                      <StreamPlayer key={`${cam.id}-${quality}`} path={`/api/cameras/${cam.id}/live?quality=${quality}`} live autoReconnect />
                      <div className="tile-bar">
                        <StatusDot state={cam.state} />
                        <span className="tile-title">{cam.name}</span>
                        <span className="tile-sub">{cam.nvr_name}</span>
                        <span className="toolbar-spacer" />
                        <button type="button" className="icon-btn" title={maximized === slot ? t("Zpět do mřížky") : t("Zvětšit")} onClick={(e) => { e.stopPropagation(); setMaximized(maximized === slot ? null : slot); }}>
                          {maximized === slot ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                        </button>
                        <button type="button" className="icon-btn" title={t("Celá obrazovka")} onClick={(e) => { e.stopPropagation(); fullscreen(slot); }}>
                          <Expand size={15} />
                        </button>
                        <button type="button" className="icon-btn" title={t("Odebrat")} onClick={(e) => { e.stopPropagation(); clearSlot(slot); }}>
                          <X size={15} />
                        </button>
                      </div>
                    </>
                  ) : (
                    <div className="tile-empty">
                      <Plus size={22} />
                      <span>{selected === slot ? t("Vyberte kameru vlevo") : t("Klikněte a vyberte kameru, nebo ji sem přetáhněte")}</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
