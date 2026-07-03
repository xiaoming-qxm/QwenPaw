---
name: browser_cdp
description: "显式 CDP 话题的高级参考。普通浏览器工作使用 browser(code=...) 和 Browser.connect(...)。"
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "🔌"
    requires: {}
---

# 浏览器 CDP 参考

普通浏览器工作使用 `browser(code=...)` 和 Browser SDK：

```python
browser = await Browser.connect(context="auto")
```

只有当用户明确提到调试端口、外部工具附着、或通过 CDP 共享浏览器时，才进入本参考。CDP 是高级后端细节，不是常规自动化主路径。

需要用户已登录 Chrome 状态时使用：

```python
browser = await Browser.connect(context="user")
```

该路径依赖 Chrome Extension bridge。若 bridge 未连接，明确阻断并请用户启用或刷新扩展。不要把用户登录态任务改路由到 isolated backend。

公开网页检索、不需要用户状态时使用：

```python
browser = await Browser.connect(context="isolated")
```

SDK 的 backend 选择独立于 API 层级：无论使用 `tab.snapshot()` 这类 primitive，还是 `tab.actions.click(...)` 这类结构化 action，都运行在选定 backend 上。
