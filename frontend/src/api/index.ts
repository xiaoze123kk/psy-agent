import { ApiClient } from "./client";
import { CounselingApi } from "./endpoints";
import { tokenStore } from "./tokenStore";
import type { RefreshTokenResponse } from "../types/api";

const DEFAULT_API_BASE_URL = "";

function getApiBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL;
}

async function refreshAuthToken(baseUrl: string): Promise<boolean> {
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
  });

  if (!response.ok) {
    tokenStore.clearAccessToken();
    return false;
  }

  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    tokenStore.clearAccessToken();
    return false;
  }

  const result = (await response.json()) as RefreshTokenResponse;
  tokenStore.setAccessToken(result.access_token);
  return true;
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
