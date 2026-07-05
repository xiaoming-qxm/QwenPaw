---
name: browser-sdk
description: "通过 browser(code=...) 使用统一 Browser SDK，处理网页检索、标签页操作和用户 Chrome 任务。"
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🌐"
    requires: {}
---

# Browser SDK

正常浏览器自动化只使用 `browser(code=...)`。在代码里连接 SDK：

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
```

按浏览器状态选择 context，不按 API 层级选择：

- `context="auto"`：默认。公开网页任务通常走 isolated backend。
- `context="user"`：通过 Chrome Extension bridge 使用用户 Chrome 登录态。若 bridge 未连接，明确阻断并汇报。
- `context="isolated"`：用于不需要用户登录态的公开网页任务。

primitive 操作和结构化 actions 是同级能力：

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.active()
await tab.actions.navigate("https://example.com")
snapshot = await tab.snapshot()
info = await tab.page_info()
await tab.actions.click({"ref": "r1_e3"})
```

通用产品能力也走结构化 actions：

```python
await tab.actions.upload({"selector": "input[type=file]"}, "/tmp/input.txt")
download = await tab.actions.download({"selector": "[data-testid=export]"})
await tab.actions.dialog(accept=True)
```

每次改变页面状态后，下一次 mutation 前必须重新调用 `tab.snapshot()` 或
`tab.screenshot()`。`tab.evaluate(..., read_only=True)` 只是读取辅助，不算新的观察。
`tab.page_info()` 只读取页面元信息，也不算新的观察。

不打开浏览器时检查后端可用性：

```python
diagnostics = await Browser.diagnostics(context="auto")
```

轻量提取使用：

```python
result = await tab.extract("总结当前可见文章", format="text")
data = await tab.extract("以 JSON 返回标题和价格", format="json")
```

Raw CDP 只属于高级内部后端能力；普通浏览器任务不要把 raw CDP 作为主路径。
