---
name: browser_visible
description: "当用户询问可见浏览器行为时使用。执行入口仍是 browser(code=...) 和 Browser SDK context。"
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "🖥️"
    requires: {}
---

# 浏览器可见性

执行入口仍然是 `browser(code=...)`。

用户需要真实 Chrome 资料、可见会话、登录态、购物车、账号页面或已有标签页时，使用 `Browser.connect(context="user")`。该路径依赖 Chrome Extension bridge；bridge 未连接时必须明确阻断。

公开网页任务不需要用户状态时，使用 `Browser.connect(context="isolated")` 或 `context="auto"`。isolated backend 是否可见由运行时配置决定；除非用户明确要求观看或协助，否则不要主动要求可见窗口。

默认静默操作。除非用户要求观看，不要前置、聚焦或激活用户的 Chrome。
