# Browser SDK Generated Help

Generated from `api_catalog.json`.

Use `Browser.capabilities(scope="actions")` for compact indexes.
Use `Browser.help(api_id="tab.actions.click")` for one API.

## Actions

- `browser.actions.search_web` - Search the public web using a supported engine.
- `tab.actions.back` - Navigate the tab backward in history.
- `tab.actions.click` - Click one target from the latest observation.
- `tab.actions.download_file` - Download a file from the page.
- `tab.actions.fill` - Fill an editable target with text.
- `tab.actions.forward` - Navigate the tab forward in history.
- `tab.actions.handle_dialog` - Handle a browser dialog.
- `tab.actions.hover` - Hover over one target from the latest observation.
- `tab.actions.navigate` - Navigate the tab to a URL.
- `tab.actions.press_key` - Press a page-level keyboard key.
- `tab.actions.reload` - Reload the current tab.
- `tab.actions.scroll` - Scroll the page or a target region.
- `tab.actions.select_option` - Select an option on a target control.
- `tab.actions.upload_file` - Upload one or more files through a target control.

## Primitives

- `browser.tabs.active` - Return the current request tab without creating one.
- `browser.tabs.list` - List browser tabs.
- `browser.tabs.new` - Explicitly create a new browser tab for the request workspace.
- `browser.tabs.open` - Reuse the request workspace tab and navigate it to a URL.
- `browser.tabs.select` - Select a tab by id.
- `tab.close` - Close or release the tab through the backend.
- `tab.extract` - Extract page data according to an instruction.
- `tab.page_info` - Read tab metadata without satisfying the observation guard.
- `tab.screenshot` - Capture a visual observation and satisfy the guard.
- `tab.snapshot` - Observe the tab and satisfy the fresh-observation guard.
- `tab.wait_for` - Wait until the page matches a structured condition.

## Diagnostics

- `browser.capabilities` - Return generated Browser SDK capabilities.
- `browser.diagnostics` - Return backend availability diagnostics without connecting.
- `browser.help` - Return generated Browser SDK help text.

## Lifecycle

- `browser.close` - Release browser session resources through the selected backend.
- `browser.connect` - Connect to a browser backend using runtime context arbitration.
