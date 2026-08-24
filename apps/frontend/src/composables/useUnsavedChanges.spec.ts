import { mount } from "@vue/test-utils";
import { defineComponent, ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ routeLeave: vi.fn() }));
vi.mock("vue-router", () => ({ onBeforeRouteLeave: mocks.routeLeave }));

import { useUnsavedChanges } from "./useUnsavedChanges";

describe("useUnsavedChanges", () => {
  beforeEach(() => {
    mocks.routeLeave.mockReset();
    vi.restoreAllMocks();
  });

  it("blocks route and browser exit only while dirty", () => {
    const dirty = ref(false);
    let confirmDiscard = () => false;
    const wrapper = mount(defineComponent({
      setup() {
        ({ confirmDiscard } = useUnsavedChanges(dirty));
        return () => null;
      },
    }));
    const guard = mocks.routeLeave.mock.calls[0][0];
    const next = vi.fn();
    guard({}, {}, next);
    expect(next).toHaveBeenCalledWith();

    dirty.value = true;
    vi.spyOn(window, "confirm").mockReturnValue(false);
    guard({}, {}, next);
    expect(next).toHaveBeenLastCalledWith(false);
    expect(confirmDiscard()).toBe(false);

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    wrapper.unmount();
  });

  it("runs the discard callback after explicit confirmation", () => {
    const dirty = ref(true);
    const discarded = vi.fn();
    let confirmDiscard = () => false;
    const wrapper = mount(defineComponent({
      setup() {
        ({ confirmDiscard } = useUnsavedChanges(dirty, { onDiscard: discarded }));
        return () => null;
      },
    }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    expect(confirmDiscard()).toBe(true);
    expect(discarded).toHaveBeenCalledOnce();
    wrapper.unmount();
  });
});
