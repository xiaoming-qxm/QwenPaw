---
name: browser
description: "通过 browser(code=...) 使用 Browser SDK，处理网页检索、标签页操作和用户 Chrome 任务。"
metadata:
  builtin_skill_version: "16.1"
  qwenpaw:
    emoji: ""
    requires: {}
---

# Browser

正常浏览器自动化使用 `browser(code=...)`。代码环境已经注入 `Browser`、
`VisualRegion`、`Grounding` 和 `TargetQuery`：不要导入 `browser_use`、`Browser` 或任何旧版浏览器包；
直接连接 Canonical Browser SDK。**VisualRegion 和 Grounding 已预注入；TargetQuery 已预注入**；绝不能写
`from browser_sdk import VisualRegion, Grounding`，它会在执行前被拒绝：

```python
browser = await Browser.connect(context="auto")
open_result = await browser.tabs.open("https://example.com")
if (
    open_result.status in {"SUCCEEDED", "PARTIAL"}
    and open_result.opened_tabs
):
    tab = await browser.tabs.select(open_result.opened_tabs[0])
    snapshot = await tab.snapshot()
```

Action-First, Controlled Primitive：

- primitive 用于标签页生命周期、观察、页面元信息、提取、等待和关闭/释放。
- `actions.*` 用于页面交互和状态改变。
- 每次改变页面状态后，下一次 mutation 前先用 `tab.snapshot()` 或
  `tab.screenshot()` 重新观察。

Canonical 值由 Runtime 签发。`opened_tabs` 中的每个元素，或
`tabs.list()` 的每个返回项，本身就是可直接传给
`browser.tabs.select(summary)` 的 `TabSummary` 选择令牌；不要访问
`summary.ref`，也不要自行构造替代令牌。需要安全元数据时使用
`summary.title`、`summary.url` 或 `summary.to_dict()`；任务刚打开标签页时，
直接选择 `open_result.opened_tabs[0]`，不要先 list 再重新寻找。已选择的 `Tab`
是操作接收器，不是元数据记录：它没有 `.url` 或 `.title`；URL/标题检查保留在
`TabSummary` 上，随后在选中的 `Tab` 上调用 `snapshot()` 获取页面证据。只使用新证据中的
`TargetRef`。每个可能改变页面的 `click` 都必须带有从**动作前**快照构造的 typed
后置条件；不要裸调用 `click(target)`：

```python
snapshot = await tab.snapshot(limit=50)
target = snapshot.targets[0]
before = snapshot.observation.context
expect = ActionExpectation.transition(
    BrowserCondition.all(PageCondition.document_changed(before))
)
terminal = await tab.actions.click(target.ref, expect=expect)
```

对于已观察到目标 URL 的链接，优先验证该 URL，而非猜测页面文本：

```python
link = None
for item in snapshot.targets:
    if item.observed_url:
        link = item
        break
if link is not None:
    expect = ActionExpectation.transition(
        BrowserCondition.all(PageCondition.url(link.observed_url, match="prefix"))
    )
    terminal = await tab.actions.click(link.ref, expect=expect)
```

向可编辑控件写入文本时，用受控 `paste`；它会验证目标最终值。之后先获取
新快照，再执行下一次 mutation：

```python
search_box = None
for item in snapshot.targets:
    if "editable" in item.states:
        search_box = item
        break
if search_box is not None:
    terminal = await tab.actions.paste(search_box.ref, "静音键盘")
    snapshot = await tab.snapshot()
```

对于虚拟化列表，请使用公开的 Canonical 滚动操作，而不是 `scroll_down` 等旧 helper。
每次整页滚动后都重新观察：

```python
terminal = await tab.actions.scroll(direction="down", amount="page")
snapshot = await tab.snapshot()
```

商品/结果页若页面顶部目标淹没了普通语义链接，优先使用已注入的 `TargetQuery`。
它采用有界语义发现、只交付匹配目标；不要仅为寻找普通链接而扩大截图或
`VisualRegion`：

```python
product_links = await tab.snapshot(
    query=TargetQuery(
        role="link",
        name="静音键盘",
        match="contains",
    ),
    limit=10,
)
product_links
```

如果某个 mutation 返回 `UNCERTAIN`、`BLOCKED` 或 `FAILED`，不要盲目重试写入。
先观察新状态，并只根据返回的 `problem` 和 `retry` 执行安全恢复。

当前 Canonical 表面尚未启用 `tab.wait_for(...)`。不要调用它，也不要使用
固定 sleep。**不要 import asyncio，也不要调用 `asyncio.sleep`（或任何固定等待）。**
页面改变或加载后直接获取新的 `tab.snapshot()`。

调用视口 `tab.screenshot()` 前，先在同一选中标签页上获取新的 `tab.snapshot()`；
该快照为图片提供证据上下文。`ScreenshotResult` 提供 task-owned `image`
`ResourceHandle`，没有本地 `.path`。不要访问截图的未承诺字段；将
`screenshot` 留作最终表达式以交付它。

当页面的商品卡片或按钮在 closed shadow DOM 中、普通快照没有可点击的语义目标时，
不要猜测 CSS、JavaScript 或原始坐标点击。先用一个小的 `snapshot(limit=50)` 建立
上下文，再取**一次**视口截图。看见图片后，立即用该截图的 `visual_context` 和图片中
目标所在的归一化矩形（0 到 1）构造 `VisualRegion`，让 SDK 把视觉区域接地为语义
`TargetRef`：

```python
snapshot = await tab.snapshot(limit=50)
visual = await tab.screenshot()
visual
```

在下一次 Browser 调用中（截图仍新鲜时）：

```python
region = VisualRegion(
    visual.visual_context,
    x=0.10, y=0.25, width=0.30, height=0.35,
)
ground = await tab.snapshot(scope=region)
if ground.grounding is Grounding.EXACT:
    target = ground.targets[0]
```

只有 `Grounding.EXACT` 提供可操作的目标；`MULTIPLE` 时缩小区域后重新接地，
`NO_MATCH`、`STALE` 或 `UNAVAILABLE` 时重新观察或停止。绝不把图片坐标直接变成
点击。为避免耗尽模型上下文，对同一页面状态复用已有观察与截图；不要为了同一目标
反复截屏或重复完整快照。

需要向模型报告结果时，将 `snapshot` 或 `terminal` 留作最终表达式。不要访问
`snapshot.observation.title` 这类未承诺属性，也不要打印原始 snapshot；只在代码中
使用 `snapshot.targets` 选择新鲜的 Runtime 签发目标。
`snapshot.targets` 中的每个元素都是 `TargetSummary`：直接读取其 `.role`、
`.name`、`.states`、`.observed_url` 与 `.ref` 字段。Browser 代码沙箱不提供
`hasattr` 这类 Python 内省 helper，不要用它探测可选字段；只使用上述已承诺字段。
目标没有 `target.observation` 对象。不要使用桌面截图工具；需要视觉上下文时，在
新 snapshot 之后将 `await tab.screenshot()` 留作最终表达式。

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
协议逃逸或直接 backend dispatcher。用新的观察结果和文档中公开的 Canonical API
恢复。
