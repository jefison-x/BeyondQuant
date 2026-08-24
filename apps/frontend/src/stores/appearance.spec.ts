import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getAppearance, updateAppearance } from "@/api/settings";
import {
  applyUiPreferences,
  DEFAULT_UI_PREFERENCES,
  readCachedUiPreferences,
  UI_PREFERENCES_CACHE_KEY,
  useAppearanceStore,
} from "./appearance";

vi.mock("@/api/settings", () => ({ getAppearance: vi.fn(), updateAppearance: vi.fn() }));

describe("appearance store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    vi.mocked(getAppearance).mockReset();
    vi.mocked(updateAppearance).mockReset();
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn() }));
  });

  it("accepts only the closed non-authoritative cache fields", () => {
    localStorage.setItem(UI_PREFERENCES_CACHE_KEY, JSON.stringify({
      schema_version: "ui-preferences.v1", color_mode: "dark", accent_theme: "ocean", user_id: "must-not-be-read",
    }));
    expect(readCachedUiPreferences()).toMatchObject({ color_mode: "dark", accent_theme: "ocean", version: 0 });
    localStorage.setItem(UI_PREFERENCES_CACHE_KEY, JSON.stringify({
      schema_version: "ui-preferences.v1", color_mode: "dark", accent_theme: "custom-red",
    }));
    expect(readCachedUiPreferences()).toBeNull();
  });

  it("applies live preview but caches only persisted preferences", () => {
    applyUiPreferences({ ...DEFAULT_UI_PREFERENCES, color_mode: "dark", accent_theme: "indigo" });
    expect(document.documentElement.dataset.resolvedMode).toBe("dark");
    expect(document.documentElement.dataset.accent).toBe("indigo");
    expect(localStorage.getItem(UI_PREFERENCES_CACHE_KEY)).toBeNull();
    applyUiPreferences({ ...DEFAULT_UI_PREFERENCES, accent_theme: "amber" }, true);
    expect(localStorage.getItem(UI_PREFERENCES_CACHE_KEY)).not.toContain("user");
  });

  it("replaces cache with Backend authority and saves optimistic version", async () => {
    vi.mocked(getAppearance).mockResolvedValue({ preferences: {
      ...DEFAULT_UI_PREFERENCES, color_mode: "light", accent_theme: "graphite", version: 3,
    } });
    vi.mocked(updateAppearance).mockResolvedValue({ preferences: {
      ...DEFAULT_UI_PREFERENCES, color_mode: "dark", accent_theme: "ocean", version: 4,
    } });
    const store = useAppearanceStore();
    await store.load();
    store.preview({ color_mode: "dark", accent_theme: "ocean" });
    await store.save();
    expect(updateAppearance).toHaveBeenCalledWith(expect.objectContaining({ expected_version: 3 }));
    expect(store.savedPreferences.version).toBe(4);
  });
});
