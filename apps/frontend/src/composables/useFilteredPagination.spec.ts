import { computed, ref } from "vue";
import { describe, expect, it } from "vitest";
import { useFilteredPagination } from "./useFilteredPagination";

describe("useFilteredPagination", () => {
  it("filters before slicing so only the active page is rendered", async () => {
    const rows = ref(Array.from({ length: 45 }, (_, index) => ({ name: `股票 ${index + 1}` })));
    const state = useFilteredPagination(computed(() => rows.value), (row) => row.name, 20);

    expect(state.pageItems.value).toHaveLength(20);
    state.page.value = 3;
    expect(state.pageItems.value).toHaveLength(5);

    state.query.value = "股票 4";
    await Promise.resolve();
    expect(state.page.value).toBe(1);
    expect(state.total.value).toBe(7);
    expect(state.pageItems.value.every((row) => row.name.includes("股票 4"))).toBe(true);
  });
});
