import type { CompanionStyleReplaceRequest } from "../types/api";

export interface CustomCompanionStyle {
  id: string;
  title: string;
  definition: string;
}

export const DEFAULT_STYLE_ID = "default";
export const NEW_STYLE_ID = "new";
export const LEGACY_STYLE_IDS = new Set(["gentle", "rational", "reflective", "action"]);
export const MAX_COMPANION_STYLE_TITLE_LENGTH = 24;
export const MAX_COMPANION_STYLE_LENGTH = 500;

const SERVER_STYLE_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function normalizeCompanionStyle(value: string) {
  const normalized = value.trim();
  if (LEGACY_STYLE_IDS.has(normalized)) return "";
  return normalized.slice(0, MAX_COMPANION_STYLE_LENGTH);
}

export function normalizeCompanionStyleTitle(value: string) {
  return value.trim().slice(0, MAX_COMPANION_STYLE_TITLE_LENGTH);
}

export function createCompanionStyleId() {
  return `custom-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function previewCompanionStyle(value: string, maxLength = 58) {
  const normalized = normalizeCompanionStyle(value);
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized;
}

export function parseCustomCompanionStyles(rawText: string, createId = createCompanionStyleId) {
  try {
    const parsed = JSON.parse(rawText) as unknown;
    if (!Array.isArray(parsed)) return [];
    const seen = new Set<string>();
    return parsed
      .map((item, index): CustomCompanionStyle | null => {
        if (!item || typeof item !== "object") return null;
        const record = item as Record<string, unknown>;
        const rawId = typeof record.id === "string" && record.id.trim() ? record.id.trim() : createId();
        if (seen.has(rawId) || rawId === DEFAULT_STYLE_ID || rawId === NEW_STYLE_ID) return null;
        const definition = normalizeCompanionStyle(typeof record.definition === "string" ? record.definition : "");
        if (!definition) return null;
        const title = normalizeCompanionStyleTitle(typeof record.title === "string" ? record.title : "") || `自定义风格 ${index + 1}`;
        seen.add(rawId);
        return { id: rawId, title, definition };
      })
      .filter((item): item is CustomCompanionStyle => Boolean(item));
  } catch {
    return [];
  }
}

export function isServerCompanionStyleId(value: string) {
  return SERVER_STYLE_ID_PATTERN.test(value);
}

export function buildCompanionStyleReplacePayload(
  styles: CustomCompanionStyle[],
  selectedStyleId: string,
): CompanionStyleReplaceRequest {
  return {
    items: styles.map((style) => ({
      style_id: isServerCompanionStyleId(style.id) ? style.id : undefined,
      client_id: style.id,
      title: normalizeCompanionStyleTitle(style.title),
      definition: normalizeCompanionStyle(style.definition),
    })),
    selected_style_id: selectedStyleId || DEFAULT_STYLE_ID,
  };
}
