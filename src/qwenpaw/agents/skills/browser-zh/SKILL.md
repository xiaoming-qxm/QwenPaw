---
name: browser
description: "通过 browser(code=...) 使用 Browser SDK，处理网页检索、标签页操作和用户 Chrome 任务。"
metadata:
  builtin_skill_version: "15.0"
  qwenpaw:
    emoji: ""
    requires: {}
---

# Browser

正常浏览器自动化使用 `browser(code=...)`。在代码里连接 Browser SDK：

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
```

Action-First, Controlled Primitive：

- primitive 用于标签页生命周期、观察、页面元信息、提取、等待和关闭/释放。
- `actions.*` 用于页面交互和状态改变。
- 每次改变页面状态后，下一次 mutation 前先用 `tab.snapshot()` 或
  `tab.screenshot()` 重新观察。

需要 API 细节时使用生成式发现入口：

```python
Browser.capabilities(scope="actions")
Browser.help(api_id="tab.actions.click")
```

常规节奏：

```python
browser = await Browser.connect(context="auto")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
await tab.actions.click({"ref": "r1_e3"})
snapshot = await tab.snapshot()
```

- `context="auto"` 是默认值，会选择当前最合适的 backend。
- `context="user"` 需要用户 Chrome bridge；不可用时明确汇报阻断。
- `context="isolated"` 用于确定性任务，且不能使用用户 Chrome 状态。
- 需要登录态、购物车、账号页面或用户已有标签页时，传入
  `requires_user_state=True`；用户 Chrome 不可用时这类请求 fail closed。

不打开浏览器时检查后端可用性：

```python
diagnostics = await Browser.diagnostics(context="auto")
```

不要使用固定 sleep、私有 backend 对象、JavaScript 执行、CSS 定位捷径、底层
协议逃逸或直接 backend dispatcher。用 `tab.wait_for(...)`、新的观察结果和
生成的 `Browser.help(...)` 恢复。
