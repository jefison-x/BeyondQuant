# dsh-byq

这是 Phase 5 DSH configuration bundle。它只添加 BeyondQuant MCP
Streamable HTTP client，并暴露 MCP tool namespace `byq`。

它有意不含 personas、skills、subagents、prompts 或 strategy agents。Bundle
通过 official `dsh plugin --profile byq add ...` mechanism 安装到 `byq`
profile。

Bundle 还拥有唯一 Product preset root。`byq-product` 是默认且唯一可选
Product preset；其 composition 有意为空，使 Product DSH 不暴露 shipped
coding presets/source-editing capabilities。Product DSH 禁用 user preset roots。
