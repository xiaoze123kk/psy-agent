export function extractApiErrorStatus(error: unknown): number | null {
  if (!(error instanceof Error)) return null;
  const match = error.message.match(/API (\d+):/);
  return match ? Number.parseInt(match[1], 10) : null;
}

export function extractApiErrorDetail(error: unknown): string | null {
  if (!(error instanceof Error)) return null;
  const match = error.message.match(/API \d+: (.+)/);
  if (!match) return null;

  try {
    const body = JSON.parse(match[1]);
    if (typeof body?.detail === "string" && body.detail.trim()) {
      return body.detail;
    }
  } catch {
    // Response body was not JSON.
  }

  return null;
}

export function getFriendlyApiError(
  error: unknown,
  fallback: string,
  statusMessages: Record<number, string>,
): string {
  const detail = extractApiErrorDetail(error);
  if (detail) return detail;

  const status = extractApiErrorStatus(error);
  return status === null ? fallback : (statusMessages[status] ?? fallback);
}
