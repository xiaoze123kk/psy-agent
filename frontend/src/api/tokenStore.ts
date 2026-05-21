let _accessToken: string | null = null;

export const tokenStore = {
  getAccessToken(): string | undefined {
    return _accessToken ?? undefined;
  },

  setAccessToken(token: string): void {
    _accessToken = token;
  },

  clearAccessToken(): void {
    _accessToken = null;
  },
};
