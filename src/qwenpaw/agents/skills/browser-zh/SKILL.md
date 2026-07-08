---
name: browser
description: "通过 browser(code=...) 使用 Browser SDK，处理网页检索、标签页操作和用户 Chrome 任务。"
metadata:
  builtin_skill_version: "14.0"
  qwenpaw:
    emoji: ""
    requires: {}
---

# Browser

正常浏览器自动化只使用 `browser(code=...)`。在代码里连接 Browser SDK：

```python
browser = await Browser.connect(context="auto", retention="clean")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
```

`retention="clean"` 是默认行为，请求结束后清理本次 workspace。调试时可以用
`retention="debug"` 保留 workspace；需要交给用户继续操作时使用
`retention="handoff"`。

长时间浏览器任务可以持续到真实终止状态。用户要求取消或外层 runtime 停止时，
使用 task cancellation 结束它。

V14 路由、workspace 和 Protocol v2 ownership 合同：

- `context="auto"`：默认。auto 优先使用用户 Chrome，也就是
  `user.chrome_extension`。只有当用户 Chrome 不可用且任务是公开或含糊
  场景时，才允许降级 isolated fallback；运行记录会保存
  `selected_backend_degraded` 与 `fallback_reason`。
- `context="user"`：显式通过 Chrome Extension bridge 使用用户 Chrome
  登录态。如果 bridge 未连接，明确阻断并汇报。
- `context="isolated"`：显式使用 isolated backend，适合确定性测试或必须
  不触碰用户 Chrome 的任务。它不会路由到用户 Chrome。

任务需要可见会话、登录态、购物车、账号页面或已有标签页时，传入
`requires_user_state=True`。这类用户状态请求在用户 Chrome 不可用时以
`user_browser_unavailable` fail closed，不会回退到 isolated。除非用户要求
观看，不要前置、聚焦或激活用户的 Chrome。

primitive 操作和结构化 actions 是同级能力：

```python
browser = await Browser.connect(context="auto", retention="clean")
tab = await browser.tabs.open("https://example.com")
snapshot = await tab.snapshot()
info = await tab.page_info()
await tab.actions.click({"ref": "r1_e3"})
```

Browser Ownership Protocol v2 的标签页语义：

- `browser.tabs.open(url)` 是普通页面任务入口。`url` 必填；它复用本次请求的
  workspace 标签页并导航到目标 URL；正常任务不会先创建空白页。
- `browser.tabs.new(url)` 只用于明确需要额外标签页的工作。`url` 必填；不要用
  URL-less new。
- `browser.tabs.active()` 只返回本请求已经控制的当前标签页；它不会创建标签页，
  也不要把它当成普通任务起点。
- `Browser.diagnostics(context="auto")` 不只检查连接，还检查 connected、
  routable、actionable 和 cleanup_verified。

通用产品能力也走结构化 actions：

```python
await tab.wait_for("商品详情加载完成", max_wait_ms=10000)
await tab.actions.fill({"selector": "input[name=q]"}, "QwenPaw")
await tab.actions.upload({"selector": "input[type=file]"}, "/tmp/input.txt")
download = await tab.actions.download({"selector": "[data-testid=export]"})
await tab.actions.dialog(accept=True)
```

每次改变页面状态后，下一次 mutation 前必须重新调用 `tab.snapshot()` 或
`tab.screenshot()`。`tab.evaluate("document.title")` 默认是只读读取；如果要执行
副作用脚本，必须显式写 `tab.evaluate(script, read_only=False)`，并遵守同样的
观察守卫。`tab.page_info()` 只读取页面元信息，也不算新的观察。

`snapshot` 可以直接转成适合模型阅读的短文本：

```python
snapshot = await tab.snapshot()
print(str(snapshot))
```

Browser approval modes 使用 QwenPaw 统一词汇：
OFF、AUTO、SMART、STRICT。只读观察属于 operational。sensitive boundary
按当前模式和证据置信度处理。critical known boundary 在所有模式都需要审批。
critical unknown boundary 直接阻断并要求用户介入。

不打开浏览器时检查后端可用性：

```python
diagnostics = await Browser.diagnostics(context="auto")
```

轻量提取使用：

```python
result = await tab.extract("总结当前可见文章", format="text")
data = await tab.extract("以 JSON 返回标题和价格", format="json")
```

Raw CDP 和远程浏览器附着是 blocked coming-soon 能力，没有公开 callable
entrypoint。普通浏览器任务走 Browser SDK。
