---
name: news
description: "Look up the latest news for the user from specified news sites. Provides authoritative URLs for politics, finance, society, world, tech, sports, and entertainment. Use browser(code=...) with the Browser SDK to open each URL, snapshot content, then summarize for the user."
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "📰"
    requires: {}
---

# News Reference

When the user asks for "latest news", "what's in the news today", or "news in category X", use **browser(code=...)** with the categories and URLs below: open the page through the Browser SDK, take a snapshot, then extract headlines and key points from the page content and reply to the user.

## Categories and Sources

| Category      | Source                    | URL |
|---------------|---------------------------|-----|
| **Politics**  | People's Daily · CPC News | https://cpc.people.com.cn/ |
| **Finance**   | China Economic Net        | http://www.ce.cn/ |
| **Society**   | China News · Society      | https://www.chinanews.com/society/ |
| **World**     | CGTN                      | https://www.cgtn.com/ |
| **Tech**      | Science and Technology Daily | https://www.stdaily.com/ |
| **Sports**    | CCTV Sports               | https://sports.cctv.com/ |
| **Entertainment** | Sina Entertainment   | https://ent.sina.com.cn/ |

## How to Use

1. **Clarify the user's need**: Determine which category or categories (politics / finance / society / world / tech / sports / entertainment), or pick 1–2 to fetch.
2. **Pick the URL**: Use the URL from the table for that category; for multiple categories, repeat the steps below for each URL.
3. **Open and observe the page**: Call **browser(code=...)** with Browser SDK code:
   ```python
   browser = await Browser.connect(context="auto")
   tab = await browser.tabs.open("https://www.chinanews.com/society/")
   snapshot = await tab.snapshot()
   print(snapshot.text)
   ```
   Replace `url` with the corresponding URL from the table.
4. **Summarize the reply**: Extract headlines, dates, and summaries from the returned page content. Organize a short list (headline + one or two sentences + source) by time or importance; if a site is unreachable or times out, say so and suggest another source.

## Notes

- Page structure may change when sites are updated; if extraction fails, say so and suggest the user open the link directly.
- When visiting multiple categories, use sequential `tabs.open(url)` navigation in the same Browser SDK working context and take a fresh snapshot after each URL, to avoid mixing content from different pages.
- You may include the original link in the reply so the user can open it.
