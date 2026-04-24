export interface ApiClientConfig {
  baseUrl: string;
  getAccessToken?: () => string | undefined;
}

export type SseEventData = Record<string, unknown>;
export type SseEventHandler = (event: string, data: SseEventData) => void;

export class ApiClient {
  private readonly baseUrl: string;
  private readonly getAccessToken?: () => string | undefined;

  constructor(config: ApiClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, "");
    this.getAccessToken = config.getAccessToken;
  }

  async get<T>(path: string): Promise<T> {
    return this.request<T>(path, { method: "GET" });
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

  async delete<T>(path: string): Promise<T> {
    return this.request<T>(path, { method: "DELETE" });
  }

  async streamPost<B = unknown>(path: string, body: B, onEvent: SseEventHandler): Promise<void> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
      headers: this.createJsonHeaders(),
    });

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

  private async request<T>(path: string, init: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: this.createJsonHeaders(init.headers),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API ${response.status}: ${errorText}`);
    }

    if (response.status === 204) {
      return {} as T;
    }

    return (await response.json()) as T;
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
