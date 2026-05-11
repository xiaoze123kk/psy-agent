import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, clearAuthTokens, tokenStore } from "../api";
import type { CurrentUserResponse } from "../types/api";

export type SessionStatus = "checking" | "authenticated" | "anonymous" | "error";

export interface SessionState {
  status: SessionStatus;
  currentUser: CurrentUserResponse | null;
  error: string | null;
}

export interface SessionContextValue extends SessionState {
  restoreSession: () => Promise<void>;
  clearSession: () => void;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

function hasStoredTokens(): boolean {
  return Boolean(tokenStore.getAccessToken() || tokenStore.getRefreshToken());
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return "Session restore failed.";
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionState>({
    status: "checking",
    currentUser: null,
    error: null,
  });

  const clearSession = useCallback(() => {
    clearAuthTokens();
    setSession({
      status: "anonymous",
      currentUser: null,
      error: null,
    });
  }, []);

  const restoreSession = useCallback(async () => {
    if (!hasStoredTokens()) {
      setSession({
        status: "anonymous",
        currentUser: null,
        error: null,
      });
      return;
    }

    setSession((current) => ({
      ...current,
      status: "checking",
      error: null,
    }));

    try {
      const currentUser = await api.getCurrentUser();
      setSession({
        status: "authenticated",
        currentUser,
        error: null,
      });
    } catch (error) {
      clearAuthTokens();
      setSession({
        status: "error",
        currentUser: null,
        error: getErrorMessage(error),
      });
    }
  }, []);

  useEffect(() => {
    void restoreSession();
  }, [restoreSession]);

  const value = useMemo<SessionContextValue>(
    () => ({
      ...session,
      restoreSession,
      clearSession,
    }),
    [clearSession, restoreSession, session],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used within SessionProvider.");
  }

  return context;
}
