# Phase 47 theme contrast matrix

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

Chrome computed the foreground/background colors from the live Product page
for every closed appearance combination. Text requires at least 4.5:1 and
chart strokes against the surface require at least 3:1. Values below are the
minimum measured ratio in each category.

| Mode | Accent | Minimum text | Minimum chart | Result |
|---|---|---:|---:|---|
| Light | Emerald | 5.21 | 5.02 | PASS |
| Light | Ocean | 5.21 | 5.02 | PASS |
| Light | Indigo | 5.21 | 5.02 | PASS |
| Light | Amber | 5.21 | 5.02 | PASS |
| Light | Graphite | 5.21 | 5.02 | PASS |
| Dark | Emerald | 5.84 | 6.98 | PASS |
| Dark | Ocean | 5.84 | 6.98 | PASS |
| Dark | Indigo | 5.84 | 6.98 | PASS |
| Dark | Amber | 5.84 | 6.98 | PASS |
| Dark | Graphite | 5.84 | 6.98 | PASS |

The chart palette is a six-token semantic contract and the browser-visible
summary remains available independently of color. Market up/down meaning is
therefore not encoded by color alone.
