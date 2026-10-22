import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, setCsrfToken, setUnauthorizedHandler } from "./lib/api";
import type { SessionPayload, Stage, User } from "./types";

type AuthStage = "loading" | "anon" | Stage;

interface AuthState {
  stage: AuthStage;
  user: User | null;
  pendingUsername: string;
  require2fa: boolean;
  recoveryCodesLeft: number | null;
}

interface AuthContextValue extends AuthState {
  applySession: (payload: SessionPayload) => void;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  setUser: (user: User) => void;
  reset: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const INITIAL: AuthState = {
  stage: "loading",
  user: null,
  pendingUsername: "",
  require2fa: true,
  recoveryCodesLeft: null,
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(INITIAL);

  const applySession = useCallback((payload: SessionPayload) => {
    setCsrfToken(payload.csrf_token);
    setState((prev) => ({
      stage: payload.stage,
      user: payload.user ?? null,
      pendingUsername: payload.username ?? payload.user?.username ?? "",
      require2fa: payload.require_2fa ?? prev.require2fa,
      recoveryCodesLeft: payload.recovery_codes_left ?? prev.recoveryCodesLeft,
    }));
  }, []);

  const reset = useCallback(() => {
    setCsrfToken("");
    setState({ ...INITIAL, stage: "anon" });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const payload = await api<SessionPayload>("/api/auth/me");
      applySession(payload);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) reset();
      else setState((prev) => (prev.stage === "loading" ? { ...INITIAL, stage: "anon" } : prev));
    }
  }, [applySession, reset]);

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {
      /* odhlášení proběhne i lokálně */
    }
    reset();
  }, [reset]);

  const setUser = useCallback((user: User) => {
    setState((prev) => ({ ...prev, user }));
  }, []);

  useEffect(() => {
    void refresh();
    setUnauthorizedHandler(() => reset());
    return () => setUnauthorizedHandler(null);
  }, [refresh, reset]);

  const value = useMemo(
    () => ({ ...state, applySession, refresh, logout, setUser, reset }),
    [state, applySession, refresh, logout, setUser, reset],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth musí být použit uvnitř AuthProvider");
  return ctx;
}
