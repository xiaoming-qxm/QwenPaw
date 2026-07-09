# Browser SDK Generated Help

Generated from `api_catalog.json`.

Use `Browser.capabilities(scope="actions")` for compact indexes.
Use `Browser.help(api_id="tab.actions.click")` for one API.

## Actions

- `browser.actions.search_web` - Search the public web using the selected backend.
- `tab.actions.back`
- `tab.actions.click`
- `tab.actions.download_file`
- `tab.actions.fill`
- `tab.actions.forward`
- `tab.actions.handle_dialog`
- `tab.actions.hover`
- `tab.actions.navigate`
- `tab.actions.press_key`
- `tab.actions.reload`
- `tab.actions.scroll`
- `tab.actions.select_option`
- `tab.actions.upload_file`

## Primitives

- `browser.tabs.active` - Return the current request tab without creating one.
- `browser.tabs.list` - List browser tabs.
- `browser.tabs.new` - Explicitly create a new browser tab for the request workspace.
- `browser.tabs.open` - Reuse the request workspace tab and navigate it to *url*.
- `browser.tabs.select` - Select a tab by id.
- `tab.close` - Close or release the tab through the backend.
- `tab.extract` - Extract lightweight text or JSON from the tab.
- `tab.page_info` - Read tab metadata without satisfying the observation guard.
- `tab.screenshot` - Capture a visual observation and satisfy the guard.
- `tab.snapshot` - Observe the tab and satisfy the fresh-observation guard.
- `tab.wait_for` - Wait until the page matches a natural-language condition.

## Diagnostics

- `browser.capabilities` - Return public Browser SDK contexts, primitives, actions, limits.
- `browser.diagnostics` - Return backend availability diagnostics without connecting.
- `browser.help` - Return generated Browser SDK help text.

## Lifecycle

- `browser.close` - Release browser session resources through the selected backend.
- `browser.connect` - Connect to a browser backend using runtime context arbitration.
