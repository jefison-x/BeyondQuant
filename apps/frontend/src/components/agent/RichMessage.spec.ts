import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import RichMessage from "./RichMessage.vue";

describe("RichMessage", () => {
  it("renders common research answer Markdown", () => {
    const wrapper = mount(RichMessage, {
      props: {
        content: "## 结论\n\n- 动量增强\n- 控制回撤\n\n`sharpe > 1`\n\n| 指标 | 数值 |\n| --- | --- |\n| 夏普 | 1.2 |",
      },
    });

    expect(wrapper.find("h2").text()).toBe("结论");
    expect(wrapper.findAll("li")).toHaveLength(2);
    expect(wrapper.find("code").text()).toBe("sharpe > 1");
    expect(wrapper.find("table").text()).toContain("夏普");
  });

  it("keeps external links safe and removes executable markup", () => {
    const wrapper = mount(RichMessage, {
      props: {
        content: "[研报](https://example.com/report) [危险](javascript:alert(1))\n\n<img src=x onerror=alert(1)><script>alert(1)</script>",
      },
    });

    const link = wrapper.find("a");
    expect(link.attributes("href")).toBe("https://example.com/report");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toBe("noopener noreferrer nofollow");
    expect(wrapper.findAll("a")).toHaveLength(1);
    expect(wrapper.find("script").exists()).toBe(false);
    expect(wrapper.find("img").exists()).toBe(false);
  });
});
