# 📈 Market News

A self-updating financial-news board. A small Python scraper pulls headlines
from major financial outlets via their RSS feeds and writes them to a JSON file;
a static site renders them as cards **grouped by source**, in the style of
[news.coroke.net](https://news.coroke.net/).

- **🔥 Highlights** at the top: the 3 companies named across the most sources
  right now, each with a short summary and links to the coverage
- **Title-only headlines**, grouped by publisher, freshest sources first
- **Top 3 per source** with a "View more" toggle to expand the rest
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

### Keeping it financial

General-business feeds (BBC, Guardian, NYT, Reuters, Bloomberg, Forbes) sometimes
carry off-topic stories. Those sources have `"filter": true`, which keeps only
headlines that match a finance term (`finance_keywords` in `sources.json`) or a
watched company — so a story like "Woman seriously injured in crash" is dropped
while "Tesla shares jump 8%" is kept. Dedicated markets feeds are left unfiltered.
Add `"filter": true` to any source to apply it, or extend `finance_keywords`.

For sites without a usable public feed, you can proxy through Google News:

```
https://news.google.com/rss/search?q=when:1d+site:example.com+markets&hl=en-US&gl=US&ceid=US:en
```

`max_items_per_source` caps how many headlines each source stores (the page
shows 3 and reveals the rest on "View more").

## Customizing the Highlights

`companies.json` is the watchlist that powers the 🔥 Highlights section. A company
is highlighted when its name appears in headlines from at least `min_sources`
different sources; the `top_n` companies with the widest coverage are shown, each
with a one-line summary pulled from the freshest article. Add entries as
`"Display Name": ["alias", "other alias"]` — aliases are matched as whole words,
case-insensitively, in the headlines:

```json
"Nvidia": ["nvidia"],
"Alphabet": ["alphabet", "google"]
```

Deliberately ambiguous words (Target, Block, Visa, Shell…) are left out so a
phrase like "price target" doesn't get mistaken for a company.

## Notes

- Headlines and links point to the original publishers; this project stores no
  article content, only titles and links from public RSS feeds.
- The hourly schedule is set in the workflow's `cron` line — adjust to taste.

Built with [Claude](https://claude.com/claude-code).
