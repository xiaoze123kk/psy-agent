import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, tokenStore } from "../api";
import { getFriendlyApiError } from "../api/errors";
import type { CurrentUserResponse, LoginRequest, RegisterRequest } from "../types/api";

const REMEMBERED_USERNAME_KEY = "warp_te.remembered_username";
const REMEMBERED_AUTO_LOGIN_KEY = "warp_te.remembered_auto_login";

let _restoringPromise: Promise<void> | null = null;

export function getRememberedUsername(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REMEMBERED_USERNAME_KEY) ?? null;
}

function setRememberedUsername(username: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(REMEMBERED_USERNAME_KEY, username);
}

function clearRememberedUsername(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(REMEMBERED_USERNAME_KEY);
}

export function getRememberedAutoLogin(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(REMEMBERED_AUTO_LOGIN_KEY) === "true";
}

function setRememberedAutoLogin(value: boolean): void {
  if (typeof window === "undefined") return;
  if (value) {
    window.localStorage.setItem(REMEMBERED_AUTO_LOGIN_KEY, "true");
  } else {
    window.localStorage.removeItem(REMEMBERED_AUTO_LOGIN_KEY);
  }
}

export type SessionStatus = "checking" | "authenticated" | "anonymous" | "error";

export interface SessionState {
  status: SessionStatus;
  currentUser: CurrentUserResponse | null;
  error: string | null;
}

export interface SessionContextValue extends SessionState {
  restoreSession: () => Promise<void>;
  clearSession: () => Promise<void>;
  login: (payload: LoginRequest) => Promise<void>;
  register: (payload: RegisterRequest) => Promise<void>;
  startDebugSession: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

function getFriendlyAuthError(error: unknown, fallback: string): string {
  return getFriendlyApiError(error, fallback, {
    400: "请求参数有误，请检查输入。",
    401: "用户名或密码错误。",
    404: "用户不存在。",
    409: "用户名已被使用。",
    422: "密码不符合要求，请检查密码规则。",
    429: "登录尝试过于频繁，请稍后再试。",
  });
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

  const clearSession = useCallback(async () => {
    tokenStore.clearAccessToken();
    clearRememberedUsername();
    setRememberedAutoLogin(false);
    try {
      await api.logout();
    } catch {
      // 即使后端调用失败也清除本地状态
    }
    setSession({
      status: "anonymous",
      currentUser: null,
      error: null,
    });
  }, []);

  const restoreSession = useCallback(async () => {
    if (_restoringPromise) return _restoringPromise;

    _restoringPromise = (async () => {
      setSession((current) => ({
        ...current,
        status: "checking",
        error: null,
      }));

      try {
        const refreshResponse = await api.refreshToken();
        tokenStore.setAccessToken(refreshResponse.access_token);
        setSession({
          status: "authenticated",
          currentUser: refreshResponse,
          error: null,
        });
      } catch {
        tokenStore.clearAccessToken();
        setSession({
          status: "anonymous",
          currentUser: null,
          error: null,
        });
      }
    })();

    try {
      await _restoringPromise;
    } finally {
      _restoringPromise = null;
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
        tokenStore.setAccessToken(response.access_token);
        setRememberedUsername(payload.username);
        setRememberedAutoLogin(payload.auto_login);
        setSession({
          status: "authenticated",
          currentUser: response,
          error: null,
        });
      } catch (error) {
        tokenStore.clearAccessToken();
        setSession({
          status: "anonymous",
          currentUser: null,
          error: getFriendlyAuthError(error, "登录失败，请检查输入。"),
        });
        throw error;
      }
    },
    [],
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
        tokenStore.setAccessToken(response.access_token);
        setRememberedUsername(payload.username);
        setRememberedAutoLogin(false);
        setSession({
          status: "authenticated",
          currentUser: response,
          error: null,
        });
      } catch (error) {
        tokenStore.clearAccessToken();
        setSession({
          status: "anonymous",
          currentUser: null,
          error: getFriendlyAuthError(error, "注册失败，请检查输入。"),
        });
        throw error;
      }
    },
    [],
  );

  const startDebugSession = useCallback(async () => {
    setSession((current) => ({
      ...current,
      status: "checking",
      error: null,
    }));

    try {
      const response = await api.devSession();
      tokenStore.setAccessToken(response.access_token);
      setSession({
        status: "authenticated",
        currentUser: response,
        error: null,
      });
    } catch (error) {
      tokenStore.clearAccessToken();
      setSession({
        status: "anonymous",
        currentUser: null,
        error: getFriendlyAuthError(error, "本地调试登录失败，请先用账号登录或注册。"),
      });
      throw error;
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
      login,
      register,
      startDebugSession,
    }),
    [clearSession, login, register, restoreSession, session, startDebugSession],
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
