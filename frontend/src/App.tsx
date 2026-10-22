import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import { AuthProvider, useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { EmptyState, PageLoader, ToastProvider } from "./components/ui";
import { hasRole } from "./lib/format";
import { AccountPage } from "./pages/Account";
import { AuditPage } from "./pages/Audit";
import { DashboardPage } from "./pages/Dashboard";
import { DeviceDetailPage } from "./pages/DeviceDetail";
import { DevicesPage } from "./pages/Devices";
import { LivePage } from "./pages/Live";
import { ForcePasswordChange, LoginPage } from "./pages/Login";
import { MonitoringPage } from "./pages/Monitoring";
import { PlaybackPage } from "./pages/Playback";
import { SettingsPage } from "./pages/Settings";
import { UsersPage } from "./pages/Users";
import type { Role } from "./types";

function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { user } = useAuth();
  if (!hasRole(user?.role, role)) {
    return (
      <EmptyState icon={<ShieldAlert size={28} />} title="Přístup odepřen">
        K této části nemáte oprávnění.
      </EmptyState>
    );
  }
  return <>{children}</>;
}

function Shell() {
  const { stage, user } = useAuth();
  if (stage === "loading") return <PageLoader />;
  if (stage !== "full" || !user) return <LoginPage />;
  if (user.must_change_password) return <ForcePasswordChange />;
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/live" element={<LivePage />} />
        <Route path="/playback" element={<RequireRole role="operator"><PlaybackPage /></RequireRole>} />
        <Route path="/monitoring" element={<MonitoringPage />} />
        <Route path="/devices" element={<DevicesPage />} />
        <Route path="/devices/:id" element={<DeviceDetailPage />} />
        <Route path="/users" element={<RequireRole role="admin"><UsersPage /></RequireRole>} />
        <Route path="/audit" element={<RequireRole role="admin"><AuditPage /></RequireRole>} />
        <Route path="/settings" element={<RequireRole role="admin"><SettingsPage /></RequireRole>} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

export function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ToastProvider>
        <AuthProvider>
          <Shell />
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}
