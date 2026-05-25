import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, clearAuthTokens, persistAuthTokens, tokenStore } from "../api";
import type { CurrentUserResponse, LoginRequest, RegisterRequest } from "../types/api";

export type SessionStatus = "checking" | "authenticated" | "anonymous" | "error";

export interface SessionState {
  status: SessionStatus;
  currentUser: CurrentUserResponse | null;
  error: string | null;
}

export interface SessionContextValue extends SessionState {
  restoreSession: () => Promise<void>;
  clearSession: () => void;
  login: (payload: LoginRequest) => Promise<void>;
  register: (payload: RegisterRequest) => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

function hasStoredTokens(): boolean {
  return Boolean(tokenStore.getAccessToken() || tokenStore.getRefreshToken());
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return "会话恢复失败。";
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

  const login = useCallback(
    async (payload: LoginRequest) => {
      setSession((current) => ({
        ...current,
        status: "checking",
        error: null,
      }));

      try {
        const response = await api.login(payload);
        persistAuthTokens({
          accessToken: response.access_token,
          refreshToken: response.refresh_token,
        });
        await restoreSession();
      } catch (error) {
        clearAuthTokens();
        setSession({
          status: "anonymous",
          currentUser: null,
          error: getErrorMessage(error),
        });
        throw error;
      }
    },
    [restoreSession],
  );

  const register = useCallback(
    async (payload: RegisterRequest) => {
      setSession((current) => ({
        ...current,
        status: "checking",
        error: null,
      }));

      try {
        const response = await api.register(payload);
        persistAuthTokens({
          accessToken: response.access_token,
          refreshToken: response.refresh_token,
        });
        await restoreSession();
      } catch (error) {
        clearAuthTokens();
        setSession({
          status: "anonymous",
          currentUser: null,
          error: getErrorMessage(error),
        });
        throw error;
      }
    },
    [restoreSession],
  );

  useEffect(() => {
    void restoreSession();
  }, [restoreSession]);

  const value = useMemo<SessionContextValue>(
    () => ({
      ...session,
      restoreSession,
      clearSession,
      login,
      register,
    }),
    [clearSession, login, register, restoreSession, session],
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
