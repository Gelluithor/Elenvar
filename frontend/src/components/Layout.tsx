import { useCallback, useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Activity,
  Film,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  ScrollText,
  Server,
  Settings,
  Sun,
  UserRound,
  Users,
  Video,
  X,
} from "lucide-react";
import { useAuth } from "../auth";
import { api } from "../lib/api";
import { hasRole, ROLE_LABELS } from "../lib/format";
import { applyTheme } from "../lib/theme";
import type { Dashboard, Role } from "../types";
import { LanguageToggle } from "./LanguageSwitch";
import { Logo } from "./Logo";
import { usePolling } from "./ui";
import { N_, t } from "../lib/i18n";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  role: Role;
  section: "watch" | "manage";
  badge?: "problems" | "update";
}

const SECTIONS = [
  { id: "watch", label: N_("Sledování") },
  { id: "manage", label: N_("Správa") },
] as const;

const NAV: NavItem[] = [
  { to: "/", label: N_("Přehled"), icon: <LayoutDashboard size={17} />, role: "viewer", section: "watch" },
  { to: "/live", label: N_("Živý obraz"), icon: <Video size={17} />, role: "viewer", section: "watch" },
  { to: "/playback", label: N_("Záznamy"), icon: <Film size={17} />, role: "operator", section: "watch" },
  { to: "/monitoring", label: N_("Monitoring"), icon: <Activity size={17} />, role: "viewer", section: "watch", badge: "problems" },
  { to: "/devices", label: N_("Zařízení"), icon: <Server size={17} />, role: "viewer", section: "manage" },
  { to: "/users", label: N_("Uživatelé"), icon: <Users size={17} />, role: "admin", section: "manage" },
  { to: "/audit", label: N_("Audit"), icon: <ScrollText size={17} />, role: "admin", section: "manage" },
  { to: "/settings", label: N_("Nastavení"), icon: <Settings size={17} />, role: "admin", section: "manage", badge: "update" },
];

type Theme = "dark" | "light";

function readTheme(): Theme {
  try {
    const saved = window.localStorage.getItem("elenvar.theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* localStorage nemusí být dostupné */
  }
  return "dark";
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    applyTheme(theme);
    try {
      window.localStorage.setItem("elenvar.theme", theme);
    } catch {
      /* ignorovat */
    }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [problems, setProblems] = useState(0);
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [theme, toggleTheme] = useTheme();
  const location = useLocation();

  const loadBadge = useCallback(() => {
    api<Dashboard>("/api/dashboard")
      .then((d) => setProblems(d.problems.length))
      .catch(() => undefined);
  }, []);

  const isAdmin = hasRole(user?.role, "admin");
  const loadUpdate = useCallback(() => {
    if (!isAdmin) return;
    api<{ update_available: boolean }>("/api/system/update")
      .then((d) => setUpdateAvailable(d.update_available))
      .catch(() => undefined);
  }, [isAdmin]);

  useEffect(() => {
    loadBadge();
    loadUpdate();
  }, [loadBadge, loadUpdate]);
  usePolling(loadBadge, 30000);
  usePolling(loadUpdate, 15 * 60 * 1000);

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  const role = user?.role;
  return (
    <div className={`shell${open ? " nav-open" : ""}`}>
      <header className="mobile-bar">
        <button type="button" className="icon-btn" onClick={() => setOpen(true)} aria-label={t("Otevřít menu")}>
          <Menu size={20} />
        </button>
        <div className="brand-inline">
          <Logo size={26} />
          <span>{t("Elenvar")}</span>
        </div>
        <span className="mobile-bar-spacer" />
      </header>

      <aside className="sidebar" aria-label={t("Hlavní navigace")}>
        <div className="sidebar-top">
          <div className="brand">
            <Logo size={34} />
            <div>
              <strong>{t("Elenvar")}</strong>
              <small>{t("Správa kamerových systémů")}</small>
            </div>
          </div>
          <button type="button" className="icon-btn sidebar-close" onClick={() => setOpen(false)} aria-label={t("Zavřít menu")}>
            <X size={20} />
          </button>
        </div>
        <nav className="nav">
          {SECTIONS.map((section) => {
            const items = NAV.filter((item) => item.section === section.id && hasRole(role, item.role));
            if (items.length === 0) return null;
            return (
              <div key={section.id} className="nav-group">
                <div className="nav-section">{t(section.label)}</div>
                {items.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.to === "/"} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>
                    {item.icon}
                    <span>{t(item.label)}</span>
                    {item.badge === "problems" && problems > 0 && <span className="nav-badge">{problems}</span>}
                    {item.badge === "update" && updateAvailable && <span className="nav-badge-dot" title={t("K dispozici je aktualizace")} />}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <NavLink to="/account" className={({ isActive }) => `user-card${isActive ? " active" : ""}`}>
            <span className="avatar">
              <UserRound size={18} />
            </span>
            <span className="user-meta">
              <strong>{user?.full_name || user?.username}</strong>
              <small>{role ? t(ROLE_LABELS[role]) : ""}</small>
            </span>
          </NavLink>
          <div className="sidebar-actions">
            <LanguageToggle />
            <button type="button" className="icon-btn" onClick={toggleTheme} aria-label={t("Přepnout motiv")} title={t("Přepnout světlý/tmavý motiv")}>
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button type="button" className="icon-btn" onClick={() => void logout()} aria-label={t("Odhlásit")} title={t("Odhlásit")}>
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </aside>
      <div className="nav-scrim" onClick={() => setOpen(false)} aria-hidden />
      <main className="content">{children}</main>
    </div>
  );
}
