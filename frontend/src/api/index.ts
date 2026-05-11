import { ApiClient } from "./client";
import { CounselingApi } from "./endpoints";
import { tokenStore, type AuthTokens } from "./tokenStore";
import type { RefreshTokenResponse } from "../types/api";

const DEFAULT_API_BASE_URL = "";

function getApiBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL;
}

async function refreshAuthToken(baseUrl: string): Promise<boolean> {
  const refreshToken = tokenStore.getRefreshToken();
  if (!refreshToken) {
    tokenStore.clearTokens();
    return false;
  }

  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/auth/refresh`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    tokenStore.clearTokens();
    return false;
  }

  const nextTokens = (await response.json()) as RefreshTokenResponse;
  tokenStore.setTokens({
    accessToken: nextTokens.access_token,
    refreshToken: nextTokens.refresh_token,
  });

  return true;
}

export function persistAuthTokens(tokens: AuthTokens): void {
  tokenStore.setTokens(tokens);
}

export function clearAuthTokens(): void {
  tokenStore.clearTokens();
}

export function createCounselingApi(baseUrl = getApiBaseUrl()): CounselingApi {
  const client = new ApiClient({
    baseUrl,
    getAccessToken: tokenStore.getAccessToken,
    onUnauthorized: () => refreshAuthToken(baseUrl),
  });

  return new CounselingApi(client);
}

export const api = createCounselingApi();

export { ApiClient } from "./client";
export { CounselingApi } from "./endpoints";
export { tokenStore };
