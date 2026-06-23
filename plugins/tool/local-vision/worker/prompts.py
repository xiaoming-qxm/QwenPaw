# -*- coding: utf-8 -*-
"""Prompt templates for UI screenshot parsing."""

UI_PARSE_PROMPT = (
    "Analyze this UI screenshot and detect ALL interactive and visible "
    "elements.\n"
    "For each element, output its type, visible text label, and bounding box "
    "coordinates.\n\n"
    "Output format: JSON array\n"
    '[{"type": "<element_type>", "text": "<visible_text>", '
    '"bbox": [x1, y1, x2, y2]}]\n\n'
    "Element types: button, link, input, checkbox, dropdown, dialog, tab, "
    "image, text, icon, other\n\n"
    "Rules:\n"
    "- bbox coordinates are in pixel units relative to the image dimensions\n"
    "- Include ALL visible buttons, links, inputs, dialogs, checkboxes, tabs\n"
    "- Include text elements that appear to be headings or labels\n"
    "- For buttons/links with icons but no text, describe the icon briefly\n"
    "- Detect modal dialogs and overlay elements with high priority\n"
    "- Order elements by visual prominence (dialogs first, then buttons, "
    "then text)\n"
)
