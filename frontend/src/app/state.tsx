import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useSession } from "./session";
import type { CurrentUserResponse, MemoryMode, UserMode } from "../types/api";

export type ThemeMode = "day" | "night";

export interface VoiceSettingsState {
  voiceEnabled: boolean;
  saveVoiceAudio: boolean;
  saveTranscript: boolean;
  companionStyle: string;
}

export interface PrivacySettingsState {
  saveVoiceAudio: boolean;
  saveTranscript: boolean;
}

export interface AppStateContextValue {
  currentUser: CurrentUserResponse | null;
  userMode: UserMode;
  memoryMode: MemoryMode;
  voiceSettings: VoiceSettingsState;
  privacySettings: PrivacySettingsState;
  themeMode: ThemeMode;
  isNight: boolean;
  setThemeMode: (mode: ThemeMode) => void;
  toggleThemeMode: () => void;
  setUserMode: (mode: UserMode) => void;
  setMemoryMode: (mode: MemoryMode) => void;
  updateVoiceSettings: (patch: Partial<VoiceSettingsState>) => void;
  updatePrivacySettings: (patch: Partial<PrivacySettingsState>) => void;
}

const AppStateContext = createContext<AppStateContextValue | undefined>(undefined);

const THEME_STORAGE_KEY = "ningyu-theme-mode";

function isThemeMode(value: string | null): value is ThemeMode {
  return value === "day" || value === "night";
}

function readInitialThemeMode(): ThemeMode {
  if (typeof window === "undefined") {
    return "day";
  }

  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  return isThemeMode(stored) ? stored : "day";
}

function buildVoiceSettings(currentUser: CurrentUserResponse | null): VoiceSettingsState {
  return {
    voiceEnabled: currentUser?.voice_enabled ?? true,
    saveVoiceAudio: currentUser?.save_voice_audio ?? false,
    saveTranscript: currentUser?.save_transcript ?? true,
    companionStyle: currentUser?.companion_style ?? "gentle",
  };
}

function buildPrivacySettings(currentUser: CurrentUserResponse | null): PrivacySettingsState {
  return {
    saveVoiceAudio: currentUser?.save_voice_audio ?? false,
    saveTranscript: currentUser?.save_transcript ?? true,
  };
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  const { currentUser } = useSession();
  const [themeMode, setThemeModeState] = useState<ThemeMode>(readInitialThemeMode);
  const [userMode, setUserModeState] = useState<UserMode>(currentUser?.user_mode ?? "teen");
  const [memoryMode, setMemoryModeState] = useState<MemoryMode>(currentUser?.memory_mode ?? "off");
  const [voiceSettings, setVoiceSettingsState] = useState<VoiceSettingsState>(() => buildVoiceSettings(currentUser));
  const [privacySettings, setPrivacySettingsState] = useState<PrivacySettingsState>(() =>
    buildPrivacySettings(currentUser),
  );

  useEffect(() => {
    if (!currentUser) {
      return;
    }

    setUserModeState(currentUser.user_mode);
    setMemoryModeState(currentUser.memory_mode);
    setVoiceSettingsState(buildVoiceSettings(currentUser));
    setPrivacySettingsState(buildPrivacySettings(currentUser));
  }, [currentUser]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);
    document.documentElement.dataset.ningyuTheme = themeMode;
  }, [themeMode]);

  const setThemeMode = useCallback((mode: ThemeMode) => {
    setThemeModeState(mode);
  }, []);

  const toggleThemeMode = useCallback(() => {
    setThemeModeState((current) => (current === "night" ? "day" : "night"));
  }, []);

  const setUserMode = useCallback((mode: UserMode) => {
    setUserModeState(mode);
  }, []);

  const setMemoryMode = useCallback((mode: MemoryMode) => {
    setMemoryModeState(mode);
  }, []);

  const updateVoiceSettings = useCallback((patch: Partial<VoiceSettingsState>) => {
    setVoiceSettingsState((current) => ({
      ...current,
      ...patch,
    }));
  }, []);

  const updatePrivacySettings = useCallback((patch: Partial<PrivacySettingsState>) => {
    setPrivacySettingsState((current) => ({
      ...current,
      ...patch,
    }));
  }, []);

  const value = useMemo<AppStateContextValue>(
    () => ({
      currentUser,
      userMode,
      memoryMode,
      voiceSettings,
      privacySettings,
      themeMode,
      isNight: themeMode === "night",
      setThemeMode,
      toggleThemeMode,
      setUserMode,
      setMemoryMode,
      updateVoiceSettings,
      updatePrivacySettings,
    }),
    [
      currentUser,
      memoryMode,
      privacySettings,
      setMemoryMode,
      setThemeMode,
      setUserMode,
      themeMode,
      toggleThemeMode,
      updatePrivacySettings,
      updateVoiceSettings,
      userMode,
      voiceSettings,
    ],
  );

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState(): AppStateContextValue {
  const context = useContext(AppStateContext);
  if (!context) {
    throw new Error("useAppState must be used within AppStateProvider.");
  }

  return context;
}
