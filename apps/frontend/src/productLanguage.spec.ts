import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("ordinary-user language boundary", () => {
  it("keeps internal engineering nouns out of the dashboard template", () => {
    const source = readFileSync(resolve(process.cwd(), "src/views/HomeView.vue"), "utf8");
    const template = source.slice(source.indexOf("<template>"), source.indexOf("</template>"));
    for (const label of ["Backend", "Artifact ID", "Job ID", "Product API", "Gateway", "WorkflowTrace"]) {
      expect(template).not.toContain(label);
    }
  });

  it("uses the modular ECharts entry rather than the all-in-one bundle", () => {
    const source = readFileSync(resolve(process.cwd(), "src/components/charts/ChartWrapper.vue"), "utf8");
    expect(source).toContain('from "echarts/core"');
    expect(source).not.toContain('import * as echarts from "echarts"');
  });
});
