"use strict";

const board = document.getElementById("board");
const indicesEl = document.getElementById("indices");
const xsumEl = document.getElementById("x-summary");
const highlightsEl = document.getElementById("highlights");
const statusEl = document.getElementById("status");
const filterEl = document.getElementById("filter");
const homeViewEl = document.getElementById("home-view");
const recapViewEl = document.getElementById("recap-view");
const viewTabEls = document.querySelectorAll(".view-tab");

const ITEMS_COLLAPSED = 3; // headlines shown per source before "view more"

let DATA = null;

/* ---------- Time formatting ---------- */
function relativeTime(ts) {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 0) return "now";
  if (diff < 60) return "now";
  if (diff < 3600) return Math.floor(diff / 60) + "m";
  if (diff < 86400) return Math.floor(diff / 3600) + "h";
  if (diff < 604800) return Math.floor(diff / 86400) + "d";
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function formatUpdated(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleString([], {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

/* ---------- Rendering ---------- */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function renderSource(source, query) {
  const group = el("section", "source-group");

  const head = el("div", "source-header");
  const fav = el("img", "favicon");
  fav.src = source.favicon;
  fav.alt = "";
  fav.loading = "lazy";
  fav.referrerPolicy = "no-referrer";
  fav.addEventListener("error", () => { fav.style.visibility = "hidden"; });
  head.appendChild(fav);
  head.appendChild(el("span", "source-name", source.name));
  head.appendChild(el("span", "source-time", relativeTime(source.latest_ts)));
  group.appendChild(head);

  const matches = query
    ? source.items.filter((i) => i.title.toLowerCase().includes(query))
    : source.items;

  if (matches.length === 0) return null; // hide sources with no matching headlines

  const list = el("ul", "news-list");
  matches.forEach((item, idx) => {
    const li = el("li", "news-item");
    // When not searching, hide everything past the first 3 until expanded.
    if (!query && idx >= ITEMS_COLLAPSED) li.classList.add("extra");
    const a = el("a", "news-link");
    a.href = item.link;
    a.target = "_blank";
    a.rel = "noopener";
    a.appendChild(el("span", "news-title", item.title));
    a.appendChild(el("span", "news-time", relativeTime(item.ts)));
    li.appendChild(a);
    list.appendChild(li);
  });
  group.appendChild(list);

  // "View more" toggle — only when collapsed items exist (i.e. not searching).
  const hiddenCount = query ? 0 : matches.length - ITEMS_COLLAPSED;
  if (hiddenCount > 0) {
    const btn = el("button", "more-btn");
    btn.type = "button";
    const labelMore = `View ${hiddenCount} more from ${source.name}`;
    btn.textContent = labelMore;
    btn.addEventListener("click", () => {
      const expanded = group.classList.toggle("expanded");
      btn.textContent = expanded ? "Show less" : labelMore;
    });
    group.appendChild(btn);
  }
  return group;
}

function tickerItem(ix) {
  const up = (ix.change ?? 0) >= 0;
  const sign = up ? "+" : "";
  const item = el("div", "ticker-item");
  item.appendChild(el("span", "ticker-name", ix.name));
  item.appendChild(
    el("span", "ticker-val",
      Number(ix.price).toLocaleString(undefined, {
        minimumFractionDigits: 2, maximumFractionDigits: 2,
      }))
  );
  item.appendChild(
    el("span", "ticker-chg " + (up ? "up" : "down"),
      `${sign}${Number(ix.change).toFixed(2)} (${sign}${Number(ix.change_pct).toFixed(2)}%)`)
  );
  return item;
}

function renderIndices(data) {
  indicesEl.innerHTML = "";
  if (!data || !Array.isArray(data.indices) || !data.indices.length) return;
  // Group into rows by `group` (e.g. US, Asia), preserving first-seen order.
  const rows = new Map();
  for (const ix of data.indices) {
    const g = ix.group || "";
    if (!rows.has(g)) rows.set(g, []);
    rows.get(g).push(ix);
  }
  for (const items of rows.values()) {
    const row = el("div", "ticker-row");
    items.forEach((ix) => row.appendChild(tickerItem(ix)));
    indicesEl.appendChild(row);
  }
}

function renderXTheme(theme, primary) {
  const card = el("div", primary ? "xsum-card" : "xsum-card xsum-card-sm");
  if (theme._subTag) {
    card.appendChild(el("div", "xsum-subtag", theme._subTag));
  }
  card.appendChild(el("div", "xsum-topic", theme.topic));
  if (theme.summary) card.appendChild(el("p", "xsum-text", theme.summary));
  if (theme.mentions && theme.mentions.length) {
    const mentions = el("div", "xsum-mentions");
    theme.mentions.slice(0, 8).forEach((m) => {
      // m is {handle, url}; tolerate the old plain-string format too.
      const raw = typeof m === "string" ? m : m.handle || "";
      const handle = raw.startsWith("@") ? raw : "@" + raw;
      const url = (typeof m === "object" && m.url)
        ? m.url
        : "https://x.com/" + handle.replace(/^@/, "");
      const a = el("a", "xsum-handle", handle);
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener";
      mentions.appendChild(a);
    });
    card.appendChild(mentions);
  }
  return card;
}

// Fixed display order of Tech sub-categories.
const TECH_SUBCATS = [
  ["infrastructure", "Infrastructure"],
  ["cloud", "Cloud"],
  ["memory", "Memory"],
  ["space", "Space"],
  ["software", "Software"],
];

function xsumHead(data) {
  const head = el("div", "xsum-head");
  head.appendChild(el("span", "xsum-title", "What X is talking about"));
  const sub = [];
  if (data.account_count) sub.push(`${data.account_count} accounts`);
  if (data.generated_at) sub.push("updated " + formatUpdated(data.generated_at));
  head.appendChild(el("span", "xsum-sub", sub.join(" · ")));
  return head;
}

function xsumGrid(themes) {
  const grid = el("div", "xsum-grid");
  themes.forEach((t) => grid.appendChild(renderXTheme(t, true)));
  return grid;
}

const CHEVRON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>';

// One collapsible category block: a clickable header + a body. Both flat and
// subsectioned categories render as a single flex-wrap grid (side-by-side, like
// Macro) so the user can see everything without extra vertical scrolling. When
// subsections are provided, each card carries its subsection label as a small
// `_subTag` so the grouping info is preserved per-card.
function xsumCategory(label, opts) {
  const sec = el("section", "xsum-cat" + (opts.variant ? " xsum-cat-" + opts.variant : ""));

  const head = el("button", "xsum-cat-head");
  head.type = "button";
  head.appendChild(el("span", "xsum-cat-label", label));
  const chev = el("span", "xsum-chev");
  chev.innerHTML = CHEVRON;
  head.appendChild(chev);

  const body = el("div", "xsum-cat-body");
  let themes;
  if (opts.subsections) {
    themes = [];
    for (const [subLabel, subThemes] of opts.subsections) {
      for (const t of subThemes) {
        themes.push({ ...t, _subTag: subLabel });
      }
    }
  } else {
    themes = opts.themes;
  }
  body.appendChild(xsumGrid(themes));

  head.addEventListener("click", () => sec.classList.toggle("collapsed"));
  sec.appendChild(head);
  sec.appendChild(body);
  return sec;
}

function renderXGrouped(data) {
  xsumEl.appendChild(xsumHead(data));
  const themes = data.themes;
  const inCat = (c) => themes.filter((t) => (t.category || "").toLowerCase() === c);

  // 1) New Topic — emergent groups (not tech/macro), pinned to the top, red.
  const other = inCat("other");
  if (other.length) {
    const groups = new Map();
    for (const t of other) {
      const key = (t.subcategory || "Other").trim() || "Other";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(t);
    }
    xsumEl.appendChild(
      xsumCategory("New Topic", { subsections: [...groups.entries()], variant: "new" })
    );
  }

  // 2) Tech — split into the fixed sub-categories (skip empty ones).
  const tech = inCat("tech");
  if (tech.length) {
    const known = new Set(TECH_SUBCATS.map(([k]) => k));
    const subsections = TECH_SUBCATS.map(([key, label]) => [
      label,
      tech.filter((t) => (t.subcategory || "").toLowerCase() === key),
    ]);
    const rest = tech.filter((t) => !known.has((t.subcategory || "").toLowerCase()));
    if (rest.length) subsections.push(["Other", rest]);
    xsumEl.appendChild(xsumCategory("Tech", { subsections }));
  }

  // 3) Macro — flat, no sub-topics.
  const macro = inCat("macro");
  if (macro.length) {
    xsumEl.appendChild(xsumCategory("Macro", { themes: macro }));
  }
}

function renderXLegacy(data) {
  xsumEl.appendChild(xsumHead(data));
  xsumEl.appendChild(xsumGrid(data.top_3));

  const others = Array.isArray(data.others) ? data.others : [];
  if (others.length) {
    const wrap = el("div", "xsum-others");
    others.forEach((t) => wrap.appendChild(renderXTheme(t, false)));
    xsumEl.appendChild(wrap);

    const btn = el("button", "xsum-more");
    btn.type = "button";
    const labelMore = `More themes (${others.length})`;
    btn.textContent = labelMore;
    btn.addEventListener("click", () => {
      const open = xsumEl.classList.toggle("xsum-open");
      btn.textContent = open ? "Show less" : labelMore;
    });
    xsumEl.appendChild(btn);
  }
}

function renderXSummary(data) {
  xsumEl.innerHTML = "";
  if (!data) return;
  if (Array.isArray(data.themes) && data.themes.length) {
    renderXGrouped(data);
  } else if (Array.isArray(data.top_3) && data.top_3.length) {
    renderXLegacy(data);
  }
}

function renderHighlights(highlights) {
  highlightsEl.innerHTML = "";
  if (!highlights || highlights.length === 0) return;

  const head = el("div", "highlights-head");
  head.appendChild(el("span", "highlights-title", "Highlights"));
  head.appendChild(
    el("span", "highlights-sub", "Most-covered companies right now")
  );
  highlightsEl.appendChild(head);

  const grid = el("div", "highlights-grid");
  highlights.forEach((h, i) => {
    const card = el("article", "highlight-card");

    const top = el("div", "highlight-top");
    top.appendChild(el("span", "highlight-rank", String(i + 1).padStart(2, "0")));
    top.appendChild(el("span", "highlight-name", h.name));
    card.appendChild(top);

    const stat = el(
      "div",
      "highlight-stat",
      `${h.source_count} sources · ${h.mentions} articles`
    );
    card.appendChild(stat);

    if (h.blurb) card.appendChild(el("p", "highlight-blurb", h.blurb));

    const list = el("ul", "highlight-list");
    for (const art of h.articles.slice(0, 3)) {
      const li = el("li");
      const a = el("a", "highlight-link");
      a.href = art.link;
      a.target = "_blank";
      a.rel = "noopener";
      const fav = el("img", "favicon-sm");
      fav.src = art.favicon;
      fav.alt = "";
      fav.loading = "lazy";
      fav.referrerPolicy = "no-referrer";
      fav.addEventListener("error", () => { fav.style.visibility = "hidden"; });
      a.appendChild(fav);

      const body = el("span", "highlight-link-body");
      body.appendChild(el("span", "highlight-link-title", art.title));
      const when = relativeTime(art.ts);
      const meta = [art.source, when].filter(Boolean).join(" · ");
      body.appendChild(el("span", "highlight-link-meta", meta));
      a.appendChild(body);
      li.appendChild(a);
      list.appendChild(li);
    }
    card.appendChild(list);
    grid.appendChild(card);
  });
  highlightsEl.appendChild(grid);
}

function render() {
  if (!DATA) return;
  const query = filterEl.value.trim().toLowerCase();
  board.innerHTML = "";

  let visibleSources = 0;
  let visibleItems = 0;
  for (const source of DATA.sources) {
    const node = renderSource(source, query);
    if (node) {
      board.appendChild(node);
      visibleSources++;
      visibleItems += node.querySelectorAll(".news-item").length;
    }
  }

  if (visibleSources === 0) {
    board.appendChild(el("div", "message", "No headlines match your filter."));
  }

  if (query) {
    statusEl.textContent =
      `${visibleItems} headline${visibleItems === 1 ? "" : "s"} matching “${query}”`;
  } else {
    statusEl.textContent =
      `${DATA.item_count} headlines from ${DATA.source_count} sources · updated ${formatUpdated(DATA.generated_at)}`;
  }
}

filterEl.addEventListener("input", render);

/* ---------- Recap view ---------- */
let RECAP_DAILY = null;
let RECAP_WEEKLY = null;
let RECAP_MODE = "daily"; // 'daily' | 'weekly'

function formatRecapDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00Z" : ""));
  if (isNaN(d)) return iso;
  return d.toLocaleDateString([], {
    year: "numeric", month: "short", day: "numeric",
  });
}

// Short label for a source chip — strip generic suffixes that bloat the chip
// without adding information ("CNBC Markets" → "cnbc", "BBC Business" → "bbc").
function sourceChipLabel(name) {
  if (!name) return "";
  let s = String(name).toLowerCase();
  s = s.replace(/\s*\(via [^)]+\)\s*/i, "");
  s = s.replace(/\s*(markets|finance|business|news)\s*$/i, "");
  s = s.replace(/\s*[·.,—]\s.+$/, "").trim();
  return s;
}

function recapSourceChip(src) {
  const a = el("a", "recap-source-chip");
  a.href = src.link;
  a.target = "_blank";
  a.rel = "noopener";
  a.title = src.source || ""; // full name in hover tooltip
  if (src.favicon) {
    const fav = el("img", "favicon-sm");
    fav.src = src.favicon;
    fav.alt = "";
    fav.loading = "lazy";
    fav.referrerPolicy = "no-referrer";
    fav.addEventListener("error", () => { fav.style.visibility = "hidden"; });
    a.appendChild(fav);
  }
  a.appendChild(document.createTextNode(sourceChipLabel(src.source)));
  return a;
}

// Build a bullet body: bold "lead", then "body" text, then every source chip
// inline at the end. Falls back to `text` if the model didn't emit lead/body.
function renderRecapBulletText(b) {
  const p = el("p", "recap-bullet-text");
  const lead = (b.lead || "").trim();
  const body = (b.body || "").trim();
  if (lead) {
    p.appendChild(el("strong", "recap-bullet-lead", lead));
  }
  if (body) {
    if (lead) p.appendChild(document.createTextNode(" "));
    p.appendChild(document.createTextNode(body));
  }
  if (!lead && !body && b.text) {
    p.appendChild(document.createTextNode(String(b.text)));
  }
  const sources = Array.isArray(b.sources) ? b.sources : [];
  if (sources.length) {
    p.appendChild(document.createTextNode(" "));
    sources.forEach((s, i) => {
      p.appendChild(recapSourceChip(s));
      if (i < sources.length - 1) p.appendChild(document.createTextNode(" "));
    });
  }
  return p;
}

function renderRecapDaily(data) {
  recapViewEl.innerHTML = "";

  const head = el("div", "recap-head");
  head.appendChild(el("span", "recap-title", "Daily recap"));
  const sub = [];
  if (data.for_date) sub.push(formatRecapDate(data.for_date));
  if (data.story_count) sub.push(`${data.story_count} headlines`);
  if (data.bucket_count) sub.push(`${data.bucket_count} themes`);
  if (data.generated_at) sub.push("updated " + formatUpdated(data.generated_at));
  head.appendChild(el("span", "recap-sub", sub.join(" · ")));
  head.appendChild(renderRecapModes());
  recapViewEl.appendChild(head);

  if (data.headline || data.summary) {
    const hero = el("div", "recap-hero");
    if (data.headline) hero.appendChild(el("h2", "recap-headline", data.headline));
    if (data.summary) hero.appendChild(el("p", "recap-summary", data.summary));
    recapViewEl.appendChild(hero);
  }

  const grid = el("div", "recap-grid");

  const sections = el("div", "recap-sections");
  const sectionList = Array.isArray(data.sections) ? data.sections : [];
  if (sectionList.length === 0) {
    sections.appendChild(el("div", "recap-empty", "No bucketed headlines yet today."));
  }
  sectionList.forEach((sec) => {
    const block = el("section", "recap-section");
    const h = el("div", "recap-section-head");
    h.appendChild(el("span", "recap-section-label", sec.label || ""));
    const bullets = Array.isArray(sec.bullets) ? sec.bullets : [];
    h.appendChild(el("span", "recap-section-meta",
      `${bullets.length} item${bullets.length === 1 ? "" : "s"}`));
    block.appendChild(h);

    const list = el("ul", "recap-bullets");
    bullets.forEach((b) => {
      const li = el("li", "recap-bullet");
      li.appendChild(renderRecapBulletText(b));
      list.appendChild(li);
    });
    block.appendChild(list);
    sections.appendChild(block);
  });
  grid.appendChild(sections);

  const side = el("aside", "recap-side");
  const watch = el("div", "recap-watch");
  watch.appendChild(el("h3", "recap-watch-head", "Watchlist"));
  const ul = el("ul", "recap-watch-list");
  const watchlist = Array.isArray(data.watchlist) ? data.watchlist : [];
  if (watchlist.length === 0) {
    ul.appendChild(el("li", "recap-watch-note", "Watchlist is empty."));
  }
  watchlist.forEach((w) => {
    const li = el("li", "recap-watch-item");
    li.appendChild(el("div", "recap-watch-name", w.name || ""));
    if (w.note) li.appendChild(el("div", "recap-watch-note", w.note));
    ul.appendChild(li);
  });
  watch.appendChild(ul);
  side.appendChild(watch);
  grid.appendChild(side);

  recapViewEl.appendChild(grid);
}

function renderRecapWeekly(data) {
  recapViewEl.innerHTML = "";

  const head = el("div", "recap-head");
  head.appendChild(el("span", "recap-title", "Weekly recap"));
  const sub = [];
  if (data.for_week_start && data.for_week_ending) {
    sub.push(`${formatRecapDate(data.for_week_start)} – ${formatRecapDate(data.for_week_ending)}`);
  } else if (data.for_week_ending) {
    sub.push(`week ending ${formatRecapDate(data.for_week_ending)}`);
  }
  if (data.days_covered != null) sub.push(`${data.days_covered} day${data.days_covered === 1 ? "" : "s"} of history`);
  if (data.generated_at) sub.push("updated " + formatUpdated(data.generated_at));
  head.appendChild(el("span", "recap-sub", sub.join(" · ")));
  head.appendChild(renderRecapModes());
  recapViewEl.appendChild(head);

  if (data.headline || data.summary) {
    const hero = el("div", "recap-hero");
    if (data.headline) hero.appendChild(el("h2", "recap-headline", data.headline));
    if (data.summary) hero.appendChild(el("p", "recap-summary", data.summary));
    recapViewEl.appendChild(hero);
  }

  const grid = el("div", "recap-grid");

  const sections = el("div", "recap-sections");
  const themes = Array.isArray(data.themes) ? data.themes : [];
  if (themes.length === 0) {
    sections.appendChild(el("div", "recap-empty",
      "Weekly recap will populate once daily recaps accumulate."));
  }
  themes.forEach((t) => {
    const block = el("section", "recap-section");
    const h = el("div", "recap-section-head");
    h.appendChild(el("span", "recap-section-label", t.label || ""));
    block.appendChild(h);
    if (t.narrative) {
      const wrap = el("ul", "recap-bullets");
      const li = el("li", "recap-bullet");
      li.appendChild(el("p", "recap-bullet-text", t.narrative));
      wrap.appendChild(li);
      block.appendChild(wrap);
    }
    const movers = Array.isArray(t.movers) ? t.movers : [];
    if (movers.length) {
      const row = el("div", "recap-movers");
      movers.slice(0, 6).forEach((m) => row.appendChild(el("span", "recap-mover", m)));
      block.appendChild(row);
    }
    sections.appendChild(block);
  });
  grid.appendChild(sections);

  const side = el("aside", "recap-side");
  const watch = el("div", "recap-watch");
  watch.appendChild(el("h3", "recap-watch-head", "Next week"));
  const ul = el("ul", "recap-watch-list");
  const watchlist = Array.isArray(data.watchlist) ? data.watchlist : [];
  if (watchlist.length === 0) {
    ul.appendChild(el("li", "recap-watch-note", "Nothing flagged."));
  }
  watchlist.forEach((w) => {
    const li = el("li", "recap-watch-item");
    li.appendChild(el("div", "recap-watch-name", w.name || ""));
    if (w.note) li.appendChild(el("div", "recap-watch-note", w.note));
    ul.appendChild(li);
  });
  watch.appendChild(ul);
  side.appendChild(watch);
  grid.appendChild(side);

  recapViewEl.appendChild(grid);
}

function renderRecapModes() {
  const wrap = el("div", "recap-modes");
  for (const [mode, label] of [["daily", "Daily"], ["weekly", "Weekly"]]) {
    const btn = el("button", "recap-mode" + (RECAP_MODE === mode ? " active" : ""), label);
    btn.type = "button";
    btn.addEventListener("click", () => {
      RECAP_MODE = mode;
      renderRecap();
    });
    wrap.appendChild(btn);
  }
  return wrap;
}

function recapEmpty(msg) {
  recapViewEl.innerHTML = "";
  const head = el("div", "recap-head");
  head.appendChild(el("span", "recap-title",
    RECAP_MODE === "weekly" ? "Weekly recap" : "Daily recap"));
  head.appendChild(renderRecapModes());
  recapViewEl.appendChild(head);
  recapViewEl.appendChild(el("div", "recap-empty", msg));
}

function renderRecap() {
  if (RECAP_MODE === "weekly") {
    if (!RECAP_WEEKLY) { recapEmpty("Weekly recap not yet generated."); return; }
    renderRecapWeekly(RECAP_WEEKLY);
  } else {
    if (!RECAP_DAILY) { recapEmpty("Daily recap not yet generated."); return; }
    renderRecapDaily(RECAP_DAILY);
  }
}

/* ---------- View routing ---------- */
function currentView() {
  return location.hash.startsWith("#/recap") ? "recap" : "home";
}

function applyView() {
  const v = currentView();
  const isRecap = v === "recap";
  homeViewEl.hidden = isRecap;
  recapViewEl.hidden = !isRecap;
  if (filterEl) filterEl.style.display = isRecap ? "none" : "";
  viewTabEls.forEach((t) => {
    t.classList.toggle("active", t.dataset.view === v);
  });
  if (isRecap) {
    renderRecap();
    statusEl.textContent = "Editorial recap — daily & weekly digest";
  } else {
    // Re-render headlines so the status line is correct.
    if (DATA) render();
  }
}

window.addEventListener("hashchange", applyView);

/* ---------- Load ---------- */
// Indices ticker loads independently and silently fails.
fetch("data/indices.json", { cache: "no-cache" })
  .then((r) => (r.ok ? r.json() : null))
  .then((data) => { if (data) renderIndices(data); })
  .catch(() => {});

// X summary loads independently — any failure must not affect the news feed.
fetch("data/x_summary.json", { cache: "no-cache" })
  .then((r) => (r.ok ? r.json() : null))
  .then((data) => { if (data) renderXSummary(data); })
  .catch(() => {});

fetch("data/news.json", { cache: "no-cache" })
  .then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  })
  .then((data) => {
    DATA = data;
    renderHighlights(data.highlights);
    if (currentView() === "home") render();
  })
  .catch((err) => {
    statusEl.textContent = "Could not load news.";
    board.innerHTML = "";
    board.appendChild(
      el("div", "message",
        "Could not load data/news.json. Run `python scraper.py` to generate it, " +
        "or wait for the scheduled update.")
    );
    console.error(err);
  });

// Recap data — independent, silent on failure. Re-renders if the user is
// already on the Recap tab when it arrives.
fetch("data/recap_daily.json", { cache: "no-cache" })
  .then((r) => (r.ok ? r.json() : null))
  .then((data) => {
    if (!data) return;
    RECAP_DAILY = data;
    if (currentView() === "recap") renderRecap();
  })
  .catch(() => {});

fetch("data/recap_weekly.json", { cache: "no-cache" })
  .then((r) => (r.ok ? r.json() : null))
  .then((data) => {
    if (!data) return;
    RECAP_WEEKLY = data;
    if (currentView() === "recap" && RECAP_MODE === "weekly") renderRecap();
  })
  .catch(() => {});

// Apply the initial view based on the URL hash (or default to home).
applyView();
