# Browser SDK Generated Help

Generated from `api_catalog.json`.

Use `Browser.capabilities(scope="actions")` for compact indexes.
Use `Browser.help(api_id="tab.actions.click")` for one API.

## Actions

- `tab.actions.back` - Navigate backward in this tab's history.
- `tab.actions.click` - Click one Runtime-issued target with closed input values.
- `tab.actions.drag` - Drag between two ordered Runtime-issued targets.
- `tab.actions.fill` - Replace the complete value of one target.
- `tab.actions.forward` - Navigate forward in this tab's history.
- `tab.actions.hover` - Hover one Runtime-issued target.
- `tab.actions.navigate` - Navigate this tab to one safe HTTP(S) URL.
- `tab.actions.press_key` - Press one closed key value on an explicit target.
- `tab.actions.reload` - Reload this exact tab.
- `tab.actions.scroll` - Scroll this tab or one Runtime-issued target.
- `tab.actions.select_option` - Select one exact OptionChoice on a target.
- `tab.actions.set_checked` - Ensure one target has the exact checked state.
- `tab.actions.type_text` - Append browser input events to one target.

## Primitives

- `browser.tabs.new` - Create one blank task tab without selecting it.
- `browser.tabs.open` - Create and navigate a task tab without selecting it.
- `tab.close` - Close this exact tab through the ActionRunner.
- `tab.print_to_pdf` - Route page PDF through ActionRunner before S8.
- `tab.read` - Read one page from an immutable bounded collection.
- `tab.screenshot` - Capture a non-mutating exact screenshot variant.
- `tab.snapshot` - Capture neutral bounded evidence for this Tab receiver.
- `tab.wait_for` - Wait for one bounded flat typed condition.

## Diagnostics


## Lifecycle

- `browser.close` - Release the current SDK lease only.
- `browser.connect` - Connect with the trusted root-task binding.
