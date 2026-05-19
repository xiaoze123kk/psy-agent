import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { buildAgeModeProfile, type AgeModeProfile } from "./ageMode";
import { useSession } from "./session";
import type { AgeRange, CurrentUserResponse, MemoryMode, UserMode } from "../types/api";

export type ThemeMode = "day" | "night";

export interface PrivacySettingsState {
  saveTranscript: boolean;
}

export interface AppStateContextValue {
  currentUser: CurrentUserResponse | null;
  ageRange: AgeRange;
  ageModeProfile: AgeModeProfile;
  userMode: UserMode;
  memoryMode: MemoryMode;
  privacySettings: PrivacySettingsState;
  themeMode: ThemeMode;
  isNight: boolean;
  setThemeMode: (mode: ThemeMode) => void;
  toggleThemeMode: () => void;
  setUserMode: (mode: UserMode) => void;
  setMemoryMode: (mode: MemoryMode) => void;
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

function buildPrivacySettings(currentUser: CurrentUserResponse | null): PrivacySettingsState {
  return {
    saveTranscript: currentUser?.save_transcript ?? true,
  };
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  const { currentUser } = useSession();
  const [themeMode, setThemeModeState] = useState<ThemeMode>(readInitialThemeMode);
  const [ageRange, setAgeRangeState] = useState<AgeRange>(currentUser?.age_range ?? "16_17");
  const [userMode, setUserModeState] = useState<UserMode>(currentUser?.user_mode ?? "teen");
  const [memoryMode, setMemoryModeState] = useState<MemoryMode>(currentUser?.memory_mode ?? "off");
  const [privacySettings, setPrivacySettingsState] = useState<PrivacySettingsState>(() =>
    buildPrivacySettings(currentUser),
  );

  useEffect(() => {
    if (!currentUser) {
      return;
    }

    setUserModeState(currentUser.user_mode);
    setAgeRangeState(currentUser.age_range);
    setMemoryModeState(currentUser.memory_mode);
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

  const updatePrivacySettings = useCallback((patch: Partial<PrivacySettingsState>) => {
    setPrivacySettingsState((current) => ({
      ...current,
      ...patch,
    }));
  }, []);

  const value = useMemo<AppStateContextValue>(
    () => ({
      currentUser,
      ageRange,
      ageModeProfile: buildAgeModeProfile(ageRange, userMode),
      userMode,
      memoryMode,
      privacySettings,
      themeMode,
      isNight: themeMode === "night",
      setThemeMode,
      toggleThemeMode,
      setUserMode,
      setMemoryMode,
      updatePrivacySettings,
    }),
    [
      ageRange,
      currentUser,
      memoryMode,
      privacySettings,
      setMemoryMode,
      setThemeMode,
      setUserMode,
      themeMode,
      toggleThemeMode,
      updatePrivacySettings,
      userMode,
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
