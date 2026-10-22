import {
  createContext,
  type CSSProperties,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CircleAlert, CircleCheck, Info, LoaderCircle, TriangleAlert, X } from "lucide-react";
import type { CameraState, NvrStatus, Severity } from "../types";
import { Logo } from "./Logo";

/* --- Spinner / prázdný stav / hlavička stránky ------------------------------ */

export function Spinner({ size = 18, label }: { size?: number; label?: string }) {
  return (
    <span className="spinner" role="status" aria-live="polite">
      <LoaderCircle size={size} className="spin" aria-hidden />
      {label ? <span>{label}</span> : <span className="sr-only">Načítání…</span>}
    </span>
  );
}

export function PageLoader() {
  return (
    <div className="page-loader" role="status" aria-live="polite">
      <Logo size={44} animated className="logo-loading" />
      <span className="sr-only">Načítání…</span>
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-icon">{icon}</div>}
      <h3>{title}</h3>
      {children && <div className="empty-body">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Alert({ kind = "error", children }: { kind?: "error" | "warning" | "info" | "success"; children: ReactNode }) {
  const Icon = kind === "error" ? CircleAlert : kind === "warning" ? TriangleAlert : kind === "success" ? CircleCheck : Info;
  return (
    <div className={`alert alert-${kind}`} role={kind === "error" ? "alert" : "status"}>
      <Icon size={18} aria-hidden />
      <div>{children}</div>
    </div>
  );
}

/* --- Stavové štítky ---------------------------------------------------------- */

const NVR_STATUS: Record<NvrStatus, { label: string; tone: string }> = {
  online: { label: "Online", tone: "ok" },
  offline: { label: "Nedostupné", tone: "bad" },
  error: { label: "Chyba", tone: "bad" },
  auth_error: { label: "Chybné přihlášení", tone: "bad" },
  unknown: { label: "Zjišťuje se", tone: "muted" },
  disabled: { label: "Vypnuto", tone: "muted" },
};

export function NvrStatusPill({ status }: { status: NvrStatus }) {
  const s = NVR_STATUS[status] ?? NVR_STATUS.unknown;
  return <span className={`pill pill-${s.tone}`}>{s.label}</span>;
}

const CAMERA_STATE: Record<CameraState, { label: string; tone: string }> = {
  online: { label: "Online", tone: "ok" },
  offline: { label: "Offline", tone: "bad" },
  unknown: { label: "Neznámý", tone: "muted" },
  nvr_down: { label: "NVR nedostupné", tone: "warn" },
};

export function CameraStatePill({ state }: { state: CameraState }) {
  const s = CAMERA_STATE[state] ?? CAMERA_STATE.unknown;
  return <span className={`pill pill-${s.tone}`}>{s.label}</span>;
}

export function StatusDot({ state }: { state: CameraState | "ok" | "bad" | "warn" | "muted" }) {
  const tone = state === "online" ? "ok" : state === "offline" ? "bad" : state === "nvr_down" ? "warn" : state === "unknown" ? "muted" : state;
  return <span className={`dot dot-${tone}`} aria-hidden />;
}

const SEVERITY: Record<Severity, { label: string; tone: string }> = {
  critical: { label: "Kritické", tone: "bad" },
  warning: { label: "Varování", tone: "warn" },
  info: { label: "Info", tone: "info" },
};

export function SeverityPill({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity];
  return <span className={`pill pill-${s.tone}`}>{s.label}</span>;
}

/* --- Formulářové prvky ------------------------------------------------------- */

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className={`field${error ? " field-error" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children(id)}
      {hint && !error && <div className="field-hint">{hint}</div>}
      {error && <div className="field-error-text">{error}</div>}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className={`switch-row${disabled ? " disabled" : ""}`}>
      <button
        type="button"
        id={id}
        role="switch"
        aria-checked={checked}
        className={`switch${checked ? " on" : ""}`}
        onClick={() => !disabled && onChange(!checked)}
        disabled={disabled}
      >
        <span className="switch-thumb" />
      </button>
      <label htmlFor={id} className="switch-text">
        <span>{label}</span>
        {description && <small>{description}</small>}
      </label>
    </div>
  );
}

/* --- Segmentový přepínač s posuvným ukazatelem -------------------------------- */

export interface SegmentOption<T> {
  value: T;
  label: ReactNode;
  title?: string;
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
  full,
}: {
  options: SegmentOption<T>[];
  value: T | null;
  onChange: (value: T) => void;
  label: string;
  full?: boolean;
}) {
  const index = options.findIndex((o) => o.value === value);
  const style = { "--seg-count": options.length, "--seg-index": Math.max(index, 0) } as CSSProperties;
  return (
    <div className={`segmented${full ? " full" : ""}`} role="radiogroup" aria-label={label} style={style}>
      {index >= 0 && <span className="seg-thumb" aria-hidden />}
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          className={o.value === value ? "active" : ""}
          title={o.title}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* --- Modální okno ------------------------------------------------------------ */

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  // Ref zajistí, že nová identita onClose (při překreslení rodiče) nespustí efekt znovu
  // a nepřesune fokus z rozepsaného pole.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = dialogRef.current;
    const focusable = node?.querySelector<HTMLElement>("input, select, textarea, button:not(.modal-close)");
    (focusable ?? node)?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    document.body.classList.add("modal-open");
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("modal-open");
      previous?.focus?.();
    };
  }, []);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`modal${wide ? " modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={dialogRef}
        tabIndex={-1}
      >
        <div className="modal-header">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-btn modal-close" onClick={onClose} aria-label="Zavřít">
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Potvrdit",
  danger,
  onConfirm,
  onClose,
}: {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => Promise<void> | void;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Akce selhala.");
      setBusy(false);
    }
  };
  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
            Zrušit
          </button>
          <button type="button" className={`btn ${danger ? "btn-danger" : "btn-primary"}`} onClick={run} disabled={busy}>
            {busy ? <Spinner size={16} /> : null}
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className="confirm-message">{message}</div>
      {error && <Alert>{error}</Alert>}
    </Modal>
  );
}

/* --- Notifikace (toasty) ----------------------------------------------------- */

interface Toast {
  id: number;
  kind: "success" | "error" | "info";
  message: string;
}

const ToastContext = createContext<(message: string, kind?: Toast["kind"]) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);
  const push = useCallback((message: string, kind: Toast["kind"] = "success") => {
    counter.current += 1;
    const id = counter.current;
    setToasts((list) => [...list.slice(-4), { id, kind, message }]);
    window.setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            {t.kind === "error" ? <CircleAlert size={18} /> : t.kind === "success" ? <CircleCheck size={18} /> : <Info size={18} />}
            <span>{t.message}</span>
            <button
              type="button"
              className="icon-btn"
              aria-label="Zavřít"
              onClick={() => setToasts((list) => list.filter((x) => x.id !== t.id))}
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

/* --- Hooky ------------------------------------------------------------------- */

/** Periodické načítání dat; pauzuje, když je karta prohlížeče skrytá. */
export function usePolling(callback: () => void, intervalMs: number, enabled = true) {
  const saved = useRef(callback);
  saved.current = callback;
  useEffect(() => {
    if (!enabled) return;
    const tick = () => {
      if (document.visibilityState === "visible") saved.current();
    };
    const handle = window.setInterval(tick, intervalMs);
    const onVisible = () => document.visibilityState === "visible" && saved.current();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(handle);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs, enabled]);
}
