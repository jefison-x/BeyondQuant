import { defineComponent, h } from "vue";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ListFilterPagination from "./ListFilterPagination.vue";

describe("ListFilterPagination", () => {
  it("emits filtering and page changes", async () => {
    const wrapper = mount(ListFilterPagination, {
      props: { query: "", page: 1, pageSize: 20, total: 45, placeholder: "筛选股票" },
      slots: { default: "<div>rows</div>" },
      global: {
        stubs: {
          "el-input": defineComponent({
            props: { modelValue: String },
            emits: ["update:modelValue"],
            setup(_, { emit }) {
              return () => h("input", { onInput: (event: Event) => emit("update:modelValue", (event.target as HTMLInputElement).value) });
            },
          }),
          EntityPagination: defineComponent({ props: { total: Number }, setup: (props) => () => h("div", String(props.total)) }),
        },
      },
    });
    await wrapper.find("input").setValue("平安");
    expect(wrapper.emitted("update:query")?.at(-1)).toEqual(["平安"]);
    expect(wrapper.text()).toContain("45");
  });
});
