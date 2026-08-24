import { defineStore } from "pinia";
import { getAppearance, updateAppearance } from "@/api/settings";
import type { AccentTheme, ColorMode, UiPreferences } from "@/api/types";

export const UI_PREFERENCES_CACHE_KEY = "byq-ui-preferences.v1";
export const COLOR_MODES: ColorMode[] = ["system", "light", "dark"];
export const ACCENT_THEMES: AccentTheme[] = ["emerald", "ocean", "indigo", "amber", "graphite"];
export const DEFAULT_UI_PREFERENCES: UiPreferences = {
  schema_version: "ui-preferences.v1",
  color_mode: "system",
  accent_theme: "emerald",
  version: 0,
  updated_at: null,
};

let activePreferences = DEFAULT_UI_PREFERENCES;
let mediaQuery: MediaQueryList | null = null;
let mediaListenerInstalled = false;

function resolvedMode(colorMode: ColorMode): "light" | "dark" {
  if (colorMode !== "system") return colorMode;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function refreshSystemMode() {
  if (activePreferences.color_mode === "system") {
    document.documentElement.dataset.resolvedMode = resolvedMode("system");
  }
}

export function readCachedUiPreferences(): UiPreferences | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(UI_PREFERENCES_CACHE_KEY) ?? "null") as Partial<UiPreferences> | null;
    if (
      parsed?.schema_version !== "ui-preferences.v1"
      || !COLOR_MODES.includes(parsed.color_mode as ColorMode)
      || !ACCENT_THEMES.includes(parsed.accent_theme as AccentTheme)
    ) return null;
    return { ...DEFAULT_UI_PREFERENCES, color_mode: parsed.color_mode!, accent_theme: parsed.accent_theme! };
  } catch {
    return null;
  }
}

export function applyUiPreferences(preferences: UiPreferences, persistCache = false) {
  activePreferences = { ...preferences };
  document.documentElement.dataset.colorMode = preferences.color_mode;
  document.documentElement.dataset.resolvedMode = resolvedMode(preferences.color_mode);
  document.documentElement.dataset.accent = preferences.accent_theme;
  document.documentElement.style.colorScheme = resolvedMode(preferences.color_mode);
  if (persistCache) {
    localStorage.setItem(UI_PREFERENCES_CACHE_KEY, JSON.stringify({
      schema_version: preferences.schema_version,
      color_mode: preferences.color_mode,
      accent_theme: preferences.accent_theme,
    }));
  }
  if (!mediaListenerInstalled && window.matchMedia) {
    mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    mediaQuery.addEventListener?.("change", refreshSystemMode);
    mediaListenerInstalled = true;
  }
}

export const useAppearanceStore = defineStore("appearance", {
  state: () => {
    const cached = readCachedUiPreferences();
    return {
      preferences: { ...(cached ?? DEFAULT_UI_PREFERENCES) } as UiPreferences,
      savedPreferences: { ...DEFAULT_UI_PREFERENCES } as UiPreferences,
      loading: false,
      saving: false,
      hydrated: false,
    };
  },
  actions: {
    async load() {
      this.loading = true;
      try {
        const response = await getAppearance();
        this.preferences = { ...response.preferences };
        this.savedPreferences = { ...response.preferences };
        this.hydrated = true;
        applyUiPreferences(this.preferences, true);
      } finally {
        this.loading = false;
      }
    },
    preview(patch: Partial<Pick<UiPreferences, "color_mode" | "accent_theme">>) {
      this.preferences = { ...this.preferences, ...patch };
      applyUiPreferences(this.preferences);
    },
    revert() {
      this.preferences = { ...this.savedPreferences };
      applyUiPreferences(this.preferences, true);
    },
    async save() {
      this.saving = true;
      try {
        const response = await updateAppearance({
          schema_version: "ui-preferences.v1",
          color_mode: this.preferences.color_mode,
          accent_theme: this.preferences.accent_theme,
          expected_version: this.savedPreferences.version,
        });
        this.preferences = { ...response.preferences };
        this.savedPreferences = { ...response.preferences };
        applyUiPreferences(this.preferences, true);
      } finally {
        this.saving = false;
      }
    },
  },
});
