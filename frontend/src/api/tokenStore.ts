export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
}

const ACCESS_TOKEN_KEY = "warp_te.access_token";
const REFRESH_TOKEN_KEY = "warp_te.refresh_token";

function getStorage(): Storage | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }

  return window.localStorage;
}

export const tokenStore = {
  getAccessToken(): string | undefined {
    return getStorage()?.getItem(ACCESS_TOKEN_KEY) ?? undefined;
  },

  getRefreshToken(): string | undefined {
    return getStorage()?.getItem(REFRESH_TOKEN_KEY) ?? undefined;
  },

  setTokens(tokens: AuthTokens): void {
    const storage = getStorage();
    if (!storage) {
      return;
    }

    storage.setItem(ACCESS_TOKEN_KEY, tokens.accessToken);
    storage.setItem(REFRESH_TOKEN_KEY, tokens.refreshToken);
  },

  clearTokens(): void {
    const storage = getStorage();
    if (!storage) {
      return;
    }

    storage.removeItem(ACCESS_TOKEN_KEY);
    storage.removeItem(REFRESH_TOKEN_KEY);
  },
};
