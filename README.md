# 📈 Market News

A self-updating financial-news board. A small Python scraper pulls headlines
from major financial outlets via their RSS feeds and writes them to a JSON file;
a static site renders them as cards **grouped by source**, in the style of
[news.coroke.net](https://news.coroke.net/).

- **Title-only headlines**, grouped by publisher, freshest sources first
- **16 sources** out of the box (CNBC, MarketWatch, WSJ, FT, Yahoo Finance,
  Reuters, Bloomberg, BBC, Guardian, NYT, The Economist, and more)
- **Live filter** box, light/dark theme, fully responsive
- **No server** — a static page plus a JSON file, auto-refreshed by GitHub Actions
  and served from GitHub Pages

## How it works

```
sources.json   ──►   scraper.py   ──►   data/news.json   ──►   index.html + app.js
 (feed list)        (fetch RSS)         (the data)            (the website)
```

`scraper.py` reads `sources.json`, fetches every RSS feed (skipping any that
fail), de-duplicates and sorts the items, and writes `data/news.json`. The page
fetches that JSON in the browser and renders it.

## Run it locally

```bash
pip install -r requirements.txt
python scraper.py            # writes data/news.json
python -m http.server 8000   # then open http://localhost:8000
```

> Open the page through a local server (as above), not by double-clicking
> `index.html` — browsers block `fetch()` of the JSON file from `file://` URLs.

## Publish to GitHub Pages

1. Create a new repository on GitHub and push this folder to it (see below).
2. In the repo, go to **Settings → Pages** and set **Source** to
   **GitHub Actions**.
3. That's it. The included workflow (`.github/workflows/deploy.yml`) runs the
   scraper and deploys the site **on every push and once an hour**, so the
   headlines stay fresh automatically. Trigger it manually anytime from the
   **Actions** tab → *Scrape & deploy* → *Run workflow*.

Your site will be live at `https://<your-username>.github.io/<repo-name>/`.

## Customizing the sources

Edit `sources.json`. Each entry needs a display `name`, a `domain` (used to fetch
the favicon), and one or more RSS `feeds`:

```json
{
  "name": "CNBC Markets",
  "domain": "cnbc.com",
  "feeds": ["https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"]
}
```

For sites without a usable public feed, you can proxy through Google News:

```
https://news.google.com/rss/search?q=when:1d+site:example.com+markets&hl=en-US&gl=US&ceid=US:en
```

`max_items_per_source` caps how many headlines each source shows.

## Notes

- Headlines and links point to the original publishers; this project stores no
  article content, only titles and links from public RSS feeds.
- The hourly schedule is set in the workflow's `cron` line — adjust to taste.

Built with [Claude](https://claude.com/claude-code).
