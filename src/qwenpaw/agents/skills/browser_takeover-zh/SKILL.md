---
name: browser_takeover
description: "当用户明确要求接管本人正在使用的 Chrome、复用现有登录态/Cookies、或需要在人机协作下操作真实浏览器标签页时，使用本 skill。"
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🐾"
    requires: {}
---

# Chrome Takeover 使用指南

`browser_use(mode="takeover")` 通过 QwenPaw Chrome Extension 与 Native Messaging 接管用户真实 Chrome。它适合需要复用用户现有登录态、已打开标签页、浏览器插件或本地会话的任务。

## 感知策略

优先使用 `snapshot` 获取 Accessibility Tree 和 ref。ref 能提供稳定目标，适合点击、输入、选择等常规网页操作。

当页面是 canvas、复杂可视化、截图验证、或 snapshot 中缺少关键目标时，再使用 `screenshot`。截图用于确认视觉状态，不应替代 ref 操作。

执行会改变页面状态的动作后，重新调用 `snapshot`。如果用户暂停后手动操作页面，恢复时必须重新感知，不要沿用暂停前的 ref。

## 操作优先级

优先级从高到低：

1. 使用 snapshot ref 执行 `click` / `type`
2. ref 失效时重新 `snapshot`
3. 仍找不到目标时使用截图辅助判断，再选择坐标点击
4. 坐标点击后再次截图或 snapshot 验证结果

不要在可以使用 ref 的情况下直接坐标点击。坐标点击只用于视觉控件、canvas、或无法暴露在 AX Tree 中的目标。

## 错误恢复

遇到 stale ref、页面跳转、弹窗、用户手动改动或 CDP 事件异常时，先重新 `snapshot`。

如果 Extension bridge 断开，停止当前 takeover 操作，提示用户检查扩展、Native Messaging host 和 Chrome 状态。不要自动切回 headless 模式复用用户登录态。

如果用户点击暂停，立即停止发送 CDP 命令。恢复后重新 snapshot，并基于新状态继续。

## 模式触发

使用 takeover 的条件：

- 用户明确说“接管我的 Chrome”“用我已经登录的浏览器”“操作当前标签页”
- 任务依赖用户真实 Chrome 中的登录态、Cookies、扩展或打开页面
- 需要用户随时暂停、手动操作、再让 agent 继续

不使用 takeover 的条件：

- 普通网页抓取、截图、表单测试可以用默认 Playwright
- 用户要求隔离环境或不暴露真实浏览器数据
- 任务不需要现有登录态

默认建议：除非用户明确需要真实 Chrome 状态，否则使用普通 `browser_use`；需要可见窗口时优先考虑 `headed=true`，需要真实用户会话时才使用 `mode="takeover"`。
