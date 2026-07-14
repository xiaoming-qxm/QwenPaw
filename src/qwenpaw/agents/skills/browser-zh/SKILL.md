---
name: browser
description: "通过 browser(code=...) 使用 Browser SDK，处理网页检索、标签页操作和用户 Chrome 任务。"
metadata:
  builtin_skill_version: "15.2"
  qwenpaw:
    emoji: ""
    requires: {}
---

# Browser

正常浏览器自动化使用 `browser(code=...)`。在代码里连接 Canonical Browser SDK：

```python
browser = await Browser.connect(context="auto")
open_result = await browser.tabs.open("https://example.com")
if (
    open_result.status in {"SUCCEEDED", "PARTIAL"}
    and open_result.opened_tabs
):
    tabs: list[TabSummary] = await browser.tabs.list()
    tab = await browser.tabs.select(open_result.opened_tabs[0])
    snapshot = await tab.snapshot()
```

Action-First, Controlled Primitive：

- primitive 用于标签页生命周期、观察、页面元信息、提取、等待和关闭/释放。
- `actions.*` 用于页面交互和状态改变。
- 每次改变页面状态后，下一次 mutation 前先用 `tab.snapshot()` 或
  `tab.screenshot()` 重新观察。

Canonical 值由 Runtime 签发。选择 `TabSummary`，只使用新证据中的
`TargetRef`，并检查 rich terminal truth：

```python
read_result = await tab.read(limit=100)
snapshot = await tab.snapshot(limit=50)
target: TargetRef = snapshot.targets[0].ref
terminal = await tab.actions.click(target)
terminal
```

wait 必须使用 typed `BrowserCondition`，不能使用自然语言猜测：

```python
condition = BrowserCondition.all(PageCondition.ready("load"))
terminal = await tab.wait_for(condition, timeout_ms=10_000)
```

workspace 路径只转换一次，之后传递 task-owned `ResourceHandle`：

```python
resource: ResourceHandle = browser.resources.from_workspace("report.pdf")
terminal = await tab.actions.upload_file(target, (resource,))
```

- `context="auto"` 是默认值，会选择当前最合适的 backend。
- `context="user"` 需要用户 Chrome bridge；不可用时明确汇报阻断。
- `context="isolated"` 用于确定性任务，且不能使用用户 Chrome 状态。
- 需要登录态、购物车、账号页面或用户已有标签页时，使用
  `context="user"`；用户 Chrome 不可用时这类请求 fail closed。

`browser(code=...)` 执行模块级 async Python，代码里不要使用 `return`。
请将 SDK 结果赋给变量，或把它放在最后一个表达式；工具会自动记录
Canonical 结果。

不要使用固定 sleep、私有 backend 对象、JavaScript 执行、CSS 定位捷径、底层
协议逃逸或直接 backend dispatcher。用 typed `tab.wait_for(...)`、新的观察结果
和文档中公开的 Canonical API 恢复。
