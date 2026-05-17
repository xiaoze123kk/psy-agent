export interface ApiClientConfig {
  baseUrl: string;
  getAccessToken?: () => string | undefined;
  onUnauthorized?: () => Promise<boolean>;
}

export type SseEventData = Record<string, unknown>;
export type SseEventHandler = (event: string, data: SseEventData) => void;

export class ApiClient {
  private readonly baseUrl: string;
  private readonly getAccessToken?: () => string | undefined;
  private readonly onUnauthorized?: () => Promise<boolean>;

  constructor(config: ApiClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, "");
    this.getAccessToken = config.getAccessToken;
    this.onUnauthorized = config.onUnauthorized;
  }

  async get<T>(path: string): Promise<T> {
    return this.request<T>(path, { method: "GET" });
  }

  async getText(path: string): Promise<string> {
    return this.requestText(path, { method: "GET" });
  }

  async post<T, B = unknown>(path: string, body?: B): Promise<T> {
    return this.request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async patch<T, B = unknown>(path: string, body: B): Promise<T> {
    return this.request<T>(path, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  }

  async delete<T, B = unknown>(path: string, body?: B): Promise<T> {
    return this.request<T>(path, {
      method: "DELETE",
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async streamPost<B = unknown>(path: string, body: B, onEvent: SseEventHandler): Promise<void> {
    return this.streamPostRequest(path, body, onEvent, true);
  }

  private async streamPostRequest<B = unknown>(
    path: string,
    body: B,
    onEvent: SseEventHandler,
    allowAuthRefresh: boolean,
  ): Promise<void> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
      headers: this.createJsonHeaders(),
    });

    if (allowAuthRefresh && response.status === 401 && (await this.tryRefreshAuth())) {
      return this.streamPostRequest(path, body, onEvent, false);
    }

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API ${response.status}: ${errorText}`);
    }

    if (!response.body) {
      throw new Error("API stream response is empty");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (value) {
          buffer += decoder.decode(value, { stream: !done });
          buffer = this.consumeSseBuffer(buffer, onEvent);
        }
        if (done) {
          break;
        }
      }
    } finally {
      reader.releaseLock();
    }

    buffer += decoder.decode();
    this.consumeSseBuffer(`${buffer}\n\n`, onEvent);
  }

  private async request<T>(path: string, init: RequestInit, allowAuthRefresh = true): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: this.createJsonHeaders(init.headers),
    });

    if (allowAuthRefresh && response.status === 401 && (await this.tryRefreshAuth())) {
      return this.request<T>(path, init, false);
    }

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API ${response.status}: ${errorText}`);
    }

    if (response.status === 204) {
      return {} as T;
    }

    return await this.parseJsonResponse<T>(response);
  }

  private async requestText(path: string, init: RequestInit, allowAuthRefresh = true): Promise<string> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: this.createTextHeaders(init.headers),
    });

    if (allowAuthRefresh && response.status === 401 && (await this.tryRefreshAuth())) {
      return this.requestText(path, init, false);
    }

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API ${response.status}: ${errorText}`);
    }

    if (response.status === 204) {
      return "";
    }

    return await response.text();
  }

  private async parseJsonResponse<T>(response: Response): Promise<T> {
    const contentType = response.headers.get("Content-Type") ?? "";
    const responseText = await response.text();

    if (!responseText.trim()) {
      return {} as T;
    }

    if (!contentType.toLowerCase().includes("application/json")) {
      const preview = responseText.trim().slice(0, 80);
      throw new Error(
        preview.toLowerCase().startsWith("<!doctype") || preview.startsWith("<")
          ? "API returned HTML instead of JSON. Check VITE_API_BASE_URL or the Vite /api proxy target."
          : `API returned non-JSON response: ${preview}`,
      );
    }

    try {
      return JSON.parse(responseText) as T;
    } catch (error) {
      throw new Error(error instanceof Error ? `API returned invalid JSON: ${error.message}` : "API returned invalid JSON.");
    }
  }

  private async tryRefreshAuth(): Promise<boolean> {
    if (!this.onUnauthorized) {
      return false;
    }

    try {
      return await this.onUnauthorized();
    } catch {
      return false;
    }
  }

  private createJsonHeaders(headers?: HeadersInit): Headers {
    const nextHeaders = new Headers(headers);
    nextHeaders.set("Content-Type", "application/json");

    const token = this.getAccessToken?.();
    if (token) {
      nextHeaders.set("Authorization", `Bearer ${token}`);
    }

    return nextHeaders;
  }

  private createTextHeaders(headers?: HeadersInit): Headers {
    const nextHeaders = new Headers(headers);
    nextHeaders.set("Accept", "text/markdown");

    const token = this.getAccessToken?.();
    if (token) {
      nextHeaders.set("Authorization", `Bearer ${token}`);
    }

    return nextHeaders;
  }

  private consumeSseBuffer(buffer: string, onEvent: SseEventHandler): string {
    const normalizedBuffer = buffer.replace(/\r\n/g, "\n");
    const eventBlocks = normalizedBuffer.split("\n\n");
    const remaining = eventBlocks.pop() ?? "";

    for (const eventBlock of eventBlocks) {
      this.dispatchSseEvent(eventBlock, onEvent);
    }

    return remaining;
  }

  private dispatchSseEvent(eventBlock: string, onEvent: SseEventHandler): void {
    let eventName = "message";
    const dataLines: string[] = [];

    for (const line of eventBlock.split("\n")) {
      if (!line || line.startsWith(":")) {
        continue;
      }

      if (line.startsWith("event:")) {
        eventName = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trimStart());
      }
    }

    if (dataLines.length === 0) {
      return;
    }

    const rawData = dataLines.join("\n");
    try {
      const parsedData = JSON.parse(rawData) as unknown;
      onEvent(
        eventName,
        parsedData && typeof parsedData === "object" ? (parsedData as SseEventData) : { value: parsedData },
      );
    } catch {
      onEvent(eventName, { text: rawData });
    }
  }
}
