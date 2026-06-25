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

// AI-related industries / supply chain. Order = the order they're displayed.
const SECTORS_SUBCATS = [
  ["abf_substrate", "ABF Substrate"],
  ["optical", "Optical"],
  ["pcb", "PCB"],
  ["ccl", "CCL"],
  ["copper_foils", "Copper Foils"],
  ["glass", "Glass"],
  ["cpu", "CPU"],
  ["gpu", "GPU"],
  ["asic", "ASIC"],
  ["memory", "Memory"],
  ["hdd", "HDD"],
  ["analog", "Analog"],
  ["advanced_packaging", "Advanced Packaging"],
  ["semicap", "Semicap"],
  ["testing", "Testing"],
  ["foundry", "Foundry"],
  ["power_front", "Power Gen (FoM)"],
  ["power_behind", "Power Gen (BTM)"],
  ["liquid_cooling", "Liquid Cooling"],
  ["psu_bbu", "PSU / BBU"],
  ["mlcc", "MLCC"],
  ["ess", "ESS"],
  ["sst", "SST"],
  ["software", "Software"],
  ["t_and_d", "T&D"],
];

// Out-of-AI themes — macro, geopolitics, robotics, space, crypto, etc.
const OUT_OF_AI_SUBCATS = [
  ["800vdc", "800VDC"],
  ["robotics", "Robotics"],
  ["space", "Space"],
  ["geopolitics", "Geopolitics"],
  ["macro", "Macro"],
  ["crypto", "Crypto"],
];

// Legacy display order from the previous taxonomy — still rendered as a
// fallback so a stale x_summary.json (from before the migration) keeps
// showing something instead of going blank for one cycle.
const TECH_SUBCATS = [
  ["infrastructure", "Infrastructure"],
  ["cloud", "Cloud"],
  ["memory", "Memory"],
  ["space", "Space"],
  ["software", "Software"],
];

const CAL_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="17" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="16" y1="2" x2="16" y2="6"/></svg>';

function xsumHead(data, opts) {
  opts = opts || {};
  const head = el("div", "xsum-head");
  head.appendChild(el("span", "xsum-title", "What X is talking about"));
  const sub = [];
  if (opts.mode === "past") {
    sub.push("Snapshot · " + (opts.date || ""));
    if (data && data.account_count) sub.push(`${data.account_count} accounts`);
  } else {
    if (data && data.account_count) sub.push(`${data.account_count} accounts`);
    if (data && data.generated_at) sub.push("updated " + formatUpdated(data.generated_at));
  }
  head.appendChild(el("span", "xsum-sub", sub.join(" · ")));

  const tools = el("div", "xsum-tools");
  if (opts.mode === "past") {
    const back = el("button", "xsum-back", "← Back to today");
    back.type = "button";
    back.addEventListener("click", () => {
      X_HISTORY_DATE = null;
      X_CAL_OPEN = false;
      renderXSummary();
    });
    tools.appendChild(back);
  }
  const cal = el("button", "xsum-cal-btn" + (X_CAL_OPEN ? " active" : ""));
  cal.type = "button";
  cal.title = X_CAL_OPEN ? "Close calendar" : "Browse past days";
  cal.setAttribute("aria-label", "Browse past days");
  cal.setAttribute("aria-expanded", X_CAL_OPEN ? "true" : "false");
  cal.innerHTML = CAL_ICON;
  cal.addEventListener("click", (e) => {
    e.stopPropagation();        // don't trigger the outside-click closer
    X_CAL_OPEN = !X_CAL_OPEN;
    renderXSummary();
  });
  tools.appendChild(cal);
  head.appendChild(tools);
  return head;
}

/* ---------- X-summary history (Headlines tab) ---------- */
let X_SUMMARY_TODAY = null;            // latest live x_summary.json
let X_HISTORY_DATE = null;             // null = today, "YYYY-MM-DD" = past
let X_CAL_OPEN = false;                // calendar popover visibility
let X_HISTORY_CACHE = {};              // date -> synthesized {themes, account_count, generated_at, for_date}
let X_CAL_MONTH = null;                // {year, month0}

// Close the popover on any click outside the popover or the toggle button.
document.addEventListener("click", (e) => {
  if (!X_CAL_OPEN) return;
  if (e.target.closest(".xsum-cal-popover")) return;
  if (e.target.closest(".xsum-cal-btn")) return;
  X_CAL_OPEN = false;
  renderXSummary();
});

function loadXHistory(date) {
  fetch(`data/recap_history/${date}.json`, { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (!data) return;
      // Synthesize the x_summary shape from the recap history snapshot.
      X_HISTORY_CACHE[date] = {
        themes: Array.isArray(data.x_themes) ? data.x_themes : [],
        account_count: data.x_account_count || 0,
        generated_at: data.x_generated_at || data.generated_at || "",
        for_date: data.for_date || date,
      };
      if (X_HISTORY_DATE === date) renderXSummary();
    })
    .catch(() => {});
}

function buildXCalendar() {
  const available = new Set(((RECAP_INDEX && RECAP_INDEX.daily) || []));
  if (!X_CAL_MONTH) {
    const newest = [...available].sort().reverse()[0];
    const seed = parseDateString(newest) || new Date();
    X_CAL_MONTH = { year: seed.getFullYear(), month0: seed.getMonth() };
  }
  const { year, month0 } = X_CAL_MONTH;

  const cal = el("div", "xsum-cal");
  const nav = el("div", "xsum-cal-nav");
  const prev = el("button", "xsum-cal-step", "‹");
  prev.type = "button";
  prev.addEventListener("click", () => {
    let m = month0 - 1, y = year;
    if (m < 0) { m = 11; y -= 1; }
    X_CAL_MONTH = { year: y, month0: m };
    renderXSummary();
  });
  const label = el("span", "xsum-cal-month",
    `${MONTH_LABELS[month0]} ${year}`);
  const next = el("button", "xsum-cal-step", "›");
  next.type = "button";
  next.addEventListener("click", () => {
    let m = month0 + 1, y = year;
    if (m > 11) { m = 0; y += 1; }
    X_CAL_MONTH = { year: y, month0: m };
    renderXSummary();
  });
  nav.appendChild(prev);
  nav.appendChild(label);
  nav.appendChild(next);
  cal.appendChild(nav);

  const grid = el("div", "xsum-cal-grid");
  WEEKDAY_LABELS.forEach((w) => grid.appendChild(el("div", "xsum-cal-wd", w)));
  const firstWd = new Date(year, month0, 1).getDay();
  const daysInMonth = new Date(year, month0 + 1, 0).getDate();
  for (let i = 0; i < firstWd; i++) {
    grid.appendChild(el("div", "xsum-cal-cell empty"));
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const ds = formatDateString(new Date(year, month0, d, 12));
    const isAvail = available.has(ds);
    const cell = el(
      isAvail ? "button" : "div",
      "xsum-cal-cell" + (isAvail ? " avail" : ""),
      String(d)
    );
    if (isAvail) {
      cell.type = "button";
      cell.title = ds;
      cell.addEventListener("click", () => {
        X_HISTORY_DATE = ds;
        X_CAL_OPEN = false;   // close popover after selection
        renderXSummary();
      });
    }
    grid.appendChild(cell);
  }
  cal.appendChild(grid);
  return cal;
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

// Build a category block from a list of subcategory definitions. Each
// subcategory becomes a sub-tag on its themes' cards; empty subcategories
// are skipped so a category with only a few hot topics today stays compact.
function buildSubcatSubsections(themesArr, subcatsList) {
  const known = new Set(subcatsList.map(([k]) => k));
  const subsections = subcatsList
    .map(([key, label]) => [
      label,
      themesArr.filter((t) => (t.subcategory || "").toLowerCase() === key),
    ])
    .filter(([, arr]) => arr.length > 0);
  const rest = themesArr.filter((t) =>
    !known.has((t.subcategory || "").toLowerCase()));
  if (rest.length) subsections.push(["Other", rest]);
  return subsections;
}

function renderXGrouped(data) {
  // Kept for any callers that still expect head+body; new code paths build
  // the head separately so renderXGroupedBody can be reused for past snapshots.
  xsumEl.appendChild(xsumHead(data, { mode: "today" }));
  renderXGroupedBody(data);
}

function renderXGroupedBody(data) {
  const themes = data.themes;
  const inCat = (c) => themes.filter((t) => (t.category || "").toLowerCase() === c);

  const sectors = inCat("sectors");
  if (sectors.length) {
    const subsections = buildSubcatSubsections(sectors, SECTORS_SUBCATS);
    if (subsections.length) {
      xsumEl.appendChild(xsumCategory("Sectors", { subsections }));
    }
  }

  const outOfAI = inCat("out_of_ai");
  if (outOfAI.length) {
    const subsections = buildSubcatSubsections(outOfAI, OUT_OF_AI_SUBCATS);
    if (subsections.length) {
      xsumEl.appendChild(xsumCategory("Out of AI", { subsections }));
    }
  }

  // --- Legacy fallback for stale x_summary.json (pre-migration) ---
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
  const tech = inCat("tech");
  if (tech.length) {
    const subsections = buildSubcatSubsections(tech, TECH_SUBCATS);
    if (subsections.length) {
      xsumEl.appendChild(xsumCategory("Tech", { subsections }));
    }
  }
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
  // The first call from the fetch passes today's data; subsequent calls (from
  // calendar/back-to-today buttons) re-render the cached state with no arg.
  if (data) X_SUMMARY_TODAY = data;
  xsumEl.innerHTML = "";

  if (X_HISTORY_DATE) {
    const snap = X_HISTORY_CACHE[X_HISTORY_DATE];
    xsumEl.appendChild(xsumHead(snap || {}, { mode: "past", date: X_HISTORY_DATE }));
    if (!snap) {
      xsumEl.appendChild(el("div", "xsum-loading",
        `Loading snapshot for ${X_HISTORY_DATE}…`));
      loadXHistory(X_HISTORY_DATE);
    } else if (Array.isArray(snap.themes) && snap.themes.length) {
      renderXGroupedBody(snap);
    } else {
      xsumEl.appendChild(el("div", "xsum-loading",
        `No X chatter archived for ${X_HISTORY_DATE}.`));
    }
  } else {
    if (!X_SUMMARY_TODAY) return;
    if (Array.isArray(X_SUMMARY_TODAY.themes) && X_SUMMARY_TODAY.themes.length) {
      xsumEl.appendChild(xsumHead(X_SUMMARY_TODAY, { mode: "today" }));
      renderXGroupedBody(X_SUMMARY_TODAY);
    } else if (Array.isArray(X_SUMMARY_TODAY.top_3) && X_SUMMARY_TODAY.top_3.length) {
      renderXLegacy(X_SUMMARY_TODAY);   // legacy schema includes its own head
    }
  }

  // Floating calendar popover, anchored to the icon button. Themes stay
  // visible behind it — the popover doesn't reflow the rest of the UI.
  if (X_CAL_OPEN) {
    const tools = xsumEl.querySelector(".xsum-tools");
    if (tools) {
      const pop = el("div", "xsum-cal-popover");
      pop.appendChild(buildXCalendar());
      tools.appendChild(pop);
    }
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

filterEl.addEventListener("input", () => {
  if (currentView() === "recap") renderRecap();
  else render();
});

/* ---------- Recap view ---------- */
let RECAP_DAILY = null;          // today's daily
let RECAP_WEEKLY = null;         // today's weekly
let RECAP_INDEX = null;          // {daily:[...], weekly:[...]}
let RECAP_HISTORY_CACHE = {};    // url -> parsed json
let RECAP_MODE = "daily";        // 'daily' | 'weekly'
let RECAP_HISTORY_DATE = null;   // YYYY-MM-DD when viewing a past day, else null
let RECAP_CAL_MONTH = null;      // {year, month0} the calendar is showing

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

// X mention chip — same pill shape as a source chip, with an X glyph instead
// of a favicon. Used inline at the end of a segment when that sentence was
// driven by chatter on X rather than a news story.
function recapXChip(m) {
  const handle = (m.handle || "").replace(/^@/, "");
  const a = el("a", "recap-source-chip recap-source-chip-x");
  a.href = m.url || `https://x.com/${handle}`;
  a.target = "_blank";
  a.rel = "noopener";
  a.title = "@" + handle;
  a.appendChild(el("span", "recap-x-glyph", "𝕏"));
  a.appendChild(document.createTextNode(handle.toLowerCase()));
  return a;
}

// Appends every chip (news source first, then X) inline with single-space
// separators. Shared so daily segments and legacy bullets behave identically.
function appendInlineChips(p, sources, xMentions) {
  const srcs = Array.isArray(sources) ? sources : [];
  const xs = Array.isArray(xMentions) ? xMentions : [];
  if (!srcs.length && !xs.length) return;
  p.appendChild(document.createTextNode(" "));
  srcs.forEach((s, i) => {
    p.appendChild(recapSourceChip(s));
    if (i < srcs.length - 1 || xs.length) p.appendChild(document.createTextNode(" "));
  });
  xs.forEach((m, i) => {
    p.appendChild(recapXChip(m));
    if (i < xs.length - 1) p.appendChild(document.createTextNode(" "));
  });
}

// Build a bullet body. Three shapes supported, in priority order:
//   1) NEW — lead + segments[]: each segment renders as its own line within
//      the bullet, with the lead bolded inline at the start of segment 1.
//      Chips sit at the end of each line so they don't visually merge into
//      the next sentence's text.
//   2) LEGACY — lead + body + sources at the bullet level (older LLM output).
//   3) MIN — text + sources (heuristic / weekly themes passed through).
function renderRecapBulletText(b) {
  const lead = (b.lead || "").trim();

  if (Array.isArray(b.segments) && b.segments.length) {
    const wrap = el("div", "recap-bullet-text");
    b.segments.forEach((seg, i) => {
      const line = el("p", "recap-bullet-line");
      if (i === 0 && lead) {
        line.appendChild(el("strong", "recap-bullet-lead", lead));
        if (seg.text) line.appendChild(document.createTextNode(" "));
      }
      const txt = (seg.text || "").trim();
      if (txt) line.appendChild(document.createTextNode(txt));
      appendInlineChips(line, seg.sources, seg.x_mentions);
      wrap.appendChild(line);
    });
    return wrap;
  }

  const p = el("p", "recap-bullet-text");
  if (lead) p.appendChild(el("strong", "recap-bullet-lead", lead));
  const body = (b.body || "").trim();
  if (body) {
    if (lead) p.appendChild(document.createTextNode(" "));
    p.appendChild(document.createTextNode(body));
  }
  if (!lead && !body && b.text) {
    p.appendChild(document.createTextNode(String(b.text)));
  }
  appendInlineChips(p, b.sources, b.x_mentions);
  return p;
}

function bulletMatchesQuery(b, q) {
  if (!q) return true;
  const segParts = (Array.isArray(b.segments) ? b.segments : []).map((s) =>
    (s.text || "") + " " +
    (Array.isArray(s.sources) ? s.sources.map((x) => x.source || "").join(" ") : "") + " " +
    (Array.isArray(s.x_mentions) ? s.x_mentions.map((x) => x.handle || "").join(" ") : "")
  ).join(" ");
  const hay = (
    (b.lead || "") + " " + (b.body || "") + " " + (b.text || "") + " " +
    (Array.isArray(b.sources) ? b.sources.map((s) => s.source || "").join(" ") : "") + " " +
    (Array.isArray(b.x_mentions) ? b.x_mentions.map((s) => s.handle || "").join(" ") : "") + " " +
    segParts
  ).toLowerCase();
  return hay.includes(q);
}

function watchMatchesQuery(w, q) {
  if (!q) return true;
  return ((w.name || "") + " " + (w.note || "")).toLowerCase().includes(q);
}

function themeMatchesQuery(t, q) {
  if (!q) return true;
  const sources = Array.isArray(t.sources)
    ? t.sources.map((s) => s.source || "").join(" ")
    : "";
  return (
    (t.label || "") + " " + (t.narrative || "") + " " +
    (Array.isArray(t.movers) ? t.movers.join(" ") : "") + " " + sources
  ).toLowerCase().includes(q);
}

// Append the daily recap body (hero + indices + sections + watchlist + X
// themes) into `container`. Used both for the top-of-page (today's data)
// and inside the History pane for the selected past snapshot. Returns
// {visibleBullets, visibleSections} so the caller can update the status line.
function appendRecapDailyBody(data, query, container) {
  if (!query && (data.headline || data.summary)) {
    const hero = el("div", "recap-hero");
    if (data.headline) hero.appendChild(el("h2", "recap-headline", data.headline));
    if (data.summary) hero.appendChild(el("p", "recap-summary", data.summary));
    container.appendChild(hero);
  }

  if (!query) {
    const idxRow = renderRecapIndices(data.indices);
    if (idxRow) container.appendChild(idxRow);
  }

  const grid = el("div", "recap-grid");

  const sections = el("div", "recap-sections");
  const sectionList = Array.isArray(data.sections) ? data.sections : [];
  let visibleBullets = 0;
  let visibleSections = 0;
  sectionList.forEach((sec) => {
    const bullets = (Array.isArray(sec.bullets) ? sec.bullets : [])
      .filter((b) => bulletMatchesQuery(b, query));
    if (bullets.length === 0) return;
    visibleSections++;
    visibleBullets += bullets.length;

    const block = el("section", "recap-section");
    const h = el("div", "recap-section-head");
    h.appendChild(el("span", "recap-section-label", sec.label || ""));
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

  if (visibleSections === 0) {
    sections.appendChild(el("div", "recap-empty",
      query
        ? `No bullets match "${query}".`
        : "No bucketed headlines."));
  }
  grid.appendChild(sections);

  const side = el("aside", "recap-side");
  const watch = el("div", "recap-watch");
  watch.appendChild(el("h3", "recap-watch-head", "Watchlist"));
  const ul = el("ul", "recap-watch-list");
  const watchlist = (Array.isArray(data.watchlist) ? data.watchlist : [])
    .filter((w) => watchMatchesQuery(w, query));
  if (watchlist.length === 0) {
    ul.appendChild(el("li", "recap-watch-note",
      query ? `No watchlist match.` : "Watchlist is empty."));
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

  container.appendChild(grid);

  // X chatter is folded into the bullets above as inline chips per sentence,
  // so the daily view no longer renders a standalone X NARRATIVES section.

  return { visibleBullets, visibleSections };
}

function renderRecapDaily(data) {
  recapViewEl.innerHTML = "";
  const query = (filterEl.value || "").trim().toLowerCase();

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

  const stats = appendRecapDailyBody(data, query, recapViewEl);

  recapViewEl.appendChild(renderRecapHistoryPane());

  if (query) {
    statusEl.textContent =
      `${stats.visibleBullets} bullet${stats.visibleBullets === 1 ? "" : "s"} matching “${query}”`;
  } else {
    const parts = [];
    if (data.bucket_count) parts.push(`${data.bucket_count} themes`);
    if (data.story_count) parts.push(`${data.story_count} headlines`);
    if (data.generated_at) parts.push("updated " + formatUpdated(data.generated_at));
    statusEl.textContent = "Daily recap · " + parts.join(" · ");
  }
}

function appendRecapWeeklyBody(data, query, container) {
  if (!query && (data.headline || data.summary)) {
    const hero = el("div", "recap-hero");
    if (data.headline) hero.appendChild(el("h2", "recap-headline", data.headline));
    if (data.summary) hero.appendChild(el("p", "recap-summary", data.summary));
    container.appendChild(hero);
  }

  const grid = el("div", "recap-grid");

  const sections = el("div", "recap-sections");
  const themes = (Array.isArray(data.themes) ? data.themes : [])
    .filter((t) => themeMatchesQuery(t, query));
  if (themes.length === 0) {
    sections.appendChild(el("div", "recap-empty",
      query
        ? `No themes match "${query}".`
        : "Weekly recap will populate once daily recaps accumulate."));
  }
  themes.forEach((t) => {
    const block = el("section", "recap-section");
    const h = el("div", "recap-section-head");
    h.appendChild(el("span", "recap-section-label", t.label || ""));
    block.appendChild(h);
    if (t.narrative || (Array.isArray(t.sources) && t.sources.length)) {
      const wrap = el("ul", "recap-bullets");
      const li = el("li", "recap-bullet");
      // Same shape as daily bullets: text first, every source chip inline at
      // the end with no +N collapse. Reuse renderRecapBulletText so styling
      // and dedup behavior stay in sync.
      li.appendChild(renderRecapBulletText({
        text: t.narrative || "",
        sources: Array.isArray(t.sources) ? t.sources : [],
      }));
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
  const watchlist = (Array.isArray(data.watchlist) ? data.watchlist : [])
    .filter((w) => watchMatchesQuery(w, query));
  if (watchlist.length === 0) {
    ul.appendChild(el("li", "recap-watch-note",
      query ? `No watchlist match.` : "Nothing flagged."));
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

  container.appendChild(grid);

  const xSec = renderRecapXThemes(data.x_themes);
  if (xSec) container.appendChild(xSec);

  return { visibleThemes: themes.length };
}

function renderRecapWeekly(data) {
  recapViewEl.innerHTML = "";
  const query = (filterEl.value || "").trim().toLowerCase();

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

  const stats = appendRecapWeeklyBody(data, query, recapViewEl);

  recapViewEl.appendChild(renderRecapHistoryPane());

  if (query) {
    statusEl.textContent =
      `${stats.visibleThemes} theme${stats.visibleThemes === 1 ? "" : "s"} matching “${query}”`;
  } else {
    const parts = [];
    if (data.days_covered != null) parts.push(`${data.days_covered} day${data.days_covered === 1 ? "" : "s"} of history`);
    if (data.generated_at) parts.push("updated " + formatUpdated(data.generated_at));
    statusEl.textContent = "Weekly recap · " + parts.join(" · ");
  }
}

function renderRecapModes() {
  const wrap = el("div", "recap-modes");
  for (const [mode, label] of [["daily", "Daily"], ["weekly", "Weekly"]]) {
    const btn = el("button", "recap-mode" + (RECAP_MODE === mode ? " active" : ""), label);
    btn.type = "button";
    btn.addEventListener("click", () => {
      RECAP_MODE = mode;
      // If we're on a past snapshot, clearing the URL triggers a hashchange
      // and applyView resets RECAP_HISTORY_DATE. Otherwise just re-render.
      if (RECAP_HISTORY_DATE || location.hash !== "#/recap") {
        location.hash = "#/recap";
      } else {
        renderRecap();
      }
    });
    wrap.appendChild(btn);
  }
  return wrap;
}

/* ---------- Recap indices row ---------- */
function renderRecapIndices(items) {
  if (!Array.isArray(items) || !items.length) return null;
  const wrap = el("div", "recap-indices");
  // Group by `group` (US, Asia, …) preserving first-seen order, same as the
  // top-of-page ticker so the visual signal is identical.
  const rows = new Map();
  for (const ix of items) {
    const g = ix.group || "";
    if (!rows.has(g)) rows.set(g, []);
    rows.get(g).push(ix);
  }
  for (const arr of rows.values()) {
    const row = el("div", "ticker-row");
    arr.forEach((ix) => row.appendChild(tickerItem(ix)));
    wrap.appendChild(row);
  }
  return wrap;
}

/* ---------- X themes section in recap ---------- */
function renderRecapXThemes(themes) {
  if (!Array.isArray(themes) || !themes.length) return null;
  const sec = el("section", "recap-xthemes");
  const head = el("div", "recap-section-head recap-xthemes-head");
  head.appendChild(el("span", "recap-section-label", "X narratives"));
  head.appendChild(el("span", "recap-section-meta",
    `${themes.length} theme${themes.length === 1 ? "" : "s"}`));
  sec.appendChild(head);

  const grid = el("div", "recap-xthemes-grid");
  themes.forEach((t) => {
    const card = el("div", "recap-xtheme-card");
    if (t.subcategory) card.appendChild(el("div", "xsum-subtag", t.subcategory));
    card.appendChild(el("div", "recap-xtheme-topic", t.topic || ""));
    if (t.summary) card.appendChild(el("p", "recap-xtheme-text", t.summary));
    const mentions = Array.isArray(t.mentions) ? t.mentions : [];
    if (mentions.length) {
      const row = el("div", "recap-xtheme-mentions");
      mentions.slice(0, 12).forEach((m) => {
        const handle = m.handle || "";
        const url = m.url || "";
        const a = el("a", "recap-xhandle", handle);
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener";
        row.appendChild(a);
      });
      card.appendChild(row);
    }
    grid.appendChild(card);
  });
  sec.appendChild(grid);
  return sec;
}

/* ---------- History pane (calendar / list) ---------- */
const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_LABELS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function parseDateString(s) {
  // Parse YYYY-MM-DD as a local-noon date so the calendar grid doesn't
  // wander by a day depending on the user's timezone.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3], 12) : null;
}

function formatDateString(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function renderHistoryCalendar() {
  // Available daily dates from the index file.
  const available = new Set((RECAP_INDEX && RECAP_INDEX.daily) || []);
  if (!RECAP_CAL_MONTH) {
    // Default to the newest available date's month, else current month.
    const newest = [...available].sort().reverse()[0];
    const seed = parseDateString(newest) || new Date();
    RECAP_CAL_MONTH = { year: seed.getFullYear(), month0: seed.getMonth() };
  }
  const { year, month0 } = RECAP_CAL_MONTH;

  const pane = el("section", "recap-history");
  const head = el("div", "recap-history-head");
  head.appendChild(el("span", "recap-history-title", "History"));
  head.appendChild(el("span", "recap-history-sub",
    `${available.size} day${available.size === 1 ? "" : "s"} archived`));
  pane.appendChild(head);

  if (available.size === 0) {
    pane.appendChild(el("div", "recap-empty",
      "No daily history yet — recaps will accumulate from now."));
    return pane;
  }

  const cal = el("div", "recap-cal");
  const nav = el("div", "recap-cal-nav");
  const prev = el("button", "recap-cal-step", "‹");
  prev.type = "button";
  prev.addEventListener("click", () => {
    let m = month0 - 1, y = year;
    if (m < 0) { m = 11; y -= 1; }
    RECAP_CAL_MONTH = { year: y, month0: m };
    renderRecap();
  });
  const label = el("span", "recap-cal-month",
    `${MONTH_LABELS[month0]} ${year}`);
  const next = el("button", "recap-cal-step", "›");
  next.type = "button";
  next.addEventListener("click", () => {
    let m = month0 + 1, y = year;
    if (m > 11) { m = 0; y += 1; }
    RECAP_CAL_MONTH = { year: y, month0: m };
    renderRecap();
  });
  nav.appendChild(prev);
  nav.appendChild(label);
  nav.appendChild(next);
  cal.appendChild(nav);

  const grid = el("div", "recap-cal-grid");
  WEEKDAY_LABELS.forEach((w) =>
    grid.appendChild(el("div", "recap-cal-wd", w)));
  const firstWd = new Date(year, month0, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month0 + 1, 0).getDate();
  for (let i = 0; i < firstWd; i++) {
    grid.appendChild(el("div", "recap-cal-cell empty"));
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const ds = formatDateString(new Date(year, month0, d, 12));
    const isAvail = available.has(ds);
    const isSelected = RECAP_HISTORY_DATE === ds;
    const cell = el(
      isAvail ? "a" : "div",
      "recap-cal-cell" + (isAvail ? " avail" : "") + (isSelected ? " selected" : ""),
      String(d)
    );
    if (isAvail) {
      cell.href = `#/recap?d=${ds}`;
      cell.title = ds;
    }
    grid.appendChild(cell);
  }
  cal.appendChild(grid);
  pane.appendChild(cal);
  return pane;
}

function renderHistoryList() {
  const available = (RECAP_INDEX && RECAP_INDEX.weekly) || [];
  const pane = el("section", "recap-history");
  const head = el("div", "recap-history-head");
  head.appendChild(el("span", "recap-history-title", "History"));
  head.appendChild(el("span", "recap-history-sub",
    `${available.length} week${available.length === 1 ? "" : "s"} archived`));
  pane.appendChild(head);

  if (available.length === 0) {
    pane.appendChild(el("div", "recap-empty",
      "No weekly history yet — weekly recaps will accumulate as they run."));
    return pane;
  }

  const list = el("ul", "recap-history-weeklist");
  available.forEach((ds) => {
    const li = el("li");
    const a = el("a", "recap-history-weekitem" +
      (RECAP_HISTORY_DATE === ds ? " selected" : ""));
    a.href = `#/recap?d=${ds}`;
    const d = parseDateString(ds);
    const display = d
      ? `Week ending ${MONTH_LABELS[d.getMonth()].slice(0,3)} ${d.getDate()}, ${d.getFullYear()}`
      : ds;
    a.textContent = display;
    li.appendChild(a);
    list.appendChild(li);
  });
  pane.appendChild(list);
  return pane;
}

function renderRecapHistoryPane() {
  const pane = RECAP_MODE === "weekly" ? renderHistoryList() : renderHistoryCalendar();
  // If a date is currently selected, embed that snapshot inside the pane
  // — directly below the calendar/list — so today's recap stays on top.
  if (RECAP_HISTORY_DATE) {
    const key = RECAP_MODE + ":" + RECAP_HISTORY_DATE;
    const snap = RECAP_HISTORY_CACHE[key];

    const head = el("div", "recap-history-snap-head");
    head.appendChild(el("span", "recap-history-snap-title",
      `Snapshot · ${RECAP_HISTORY_DATE}`));
    const close = el("a", "recap-history-snap-close", "Close");
    close.href = "#/recap";
    head.appendChild(close);
    pane.appendChild(head);

    const wrap = el("div", "recap-history-snap");
    if (snap) {
      if (RECAP_MODE === "weekly") {
        appendRecapWeeklyBody(snap, "", wrap);
      } else {
        appendRecapDailyBody(snap, "", wrap);
      }
    } else {
      wrap.appendChild(el("div", "recap-empty",
        `Loading snapshot for ${RECAP_HISTORY_DATE}…`));
      loadRecapHistory(RECAP_HISTORY_DATE, RECAP_MODE);
    }
    pane.appendChild(wrap);
  }
  return pane;
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
  // Main view always renders TODAY's recap. The History pane handles its
  // own selected-date snapshot inline (see renderRecapHistoryPane).
  const data = RECAP_MODE === "weekly" ? RECAP_WEEKLY : RECAP_DAILY;
  if (!data) {
    recapEmpty(RECAP_MODE === "weekly"
      ? "Weekly recap not yet generated."
      : "Daily recap not yet generated.");
    return;
  }
  if (RECAP_MODE === "weekly") renderRecapWeekly(data);
  else renderRecapDaily(data);
}

function loadRecapHistory(date, mode) {
  const folder = mode === "weekly" ? "recap_history_weekly" : "recap_history";
  const url = `data/${folder}/${date}.json`;
  fetch(url, { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (!data) {
        recapEmpty(`No snapshot available for ${date}.`);
        return;
      }
      RECAP_HISTORY_CACHE[mode + ":" + date] = data;
      // Re-render only if the user is still on that target.
      if (RECAP_HISTORY_DATE === date && RECAP_MODE === mode) renderRecap();
    })
    .catch(() => recapEmpty(`Could not load snapshot for ${date}.`));
}

/* ---------- View routing ---------- */
function parseHashParams() {
  // Accepts "#/recap?d=2026-06-15" → {d:"2026-06-15"}. Hash is the whole
  // location.hash including the leading "#". We only care about ?<query>.
  const h = location.hash || "";
  const q = h.indexOf("?");
  if (q === -1) return {};
  const out = {};
  for (const kv of h.slice(q + 1).split("&")) {
    if (!kv) continue;
    const [k, v] = kv.split("=");
    out[decodeURIComponent(k)] = decodeURIComponent(v || "");
  }
  return out;
}

function currentView() {
  return location.hash.startsWith("#/recap") ? "recap" : "home";
}

function applyView() {
  const v = currentView();
  const isRecap = v === "recap";
  homeViewEl.hidden = isRecap;
  recapViewEl.hidden = !isRecap;
  // Filter input stays visible across views; the placeholder hints which
  // dataset it currently filters.
  if (filterEl) {
    filterEl.placeholder = isRecap ? "Filter recap…" : "Filter headlines…";
  }
  viewTabEls.forEach((t) => {
    t.classList.toggle("active", t.dataset.view === v);
  });
  if (isRecap) {
    const params = parseHashParams();
    // ?d=YYYY-MM-DD selects a past snapshot. We honor whichever mode is
    // active so the same date param works for both daily and weekly history.
    RECAP_HISTORY_DATE = /^\d{4}-\d{2}-\d{2}$/.test(params.d || "")
      ? params.d
      : null;
    renderRecap();
  } else if (DATA) {
    // Re-render headlines so the status line is correct.
    render();
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

// Index of available history dates, drives the calendar / weekly list.
fetch("data/recap_index.json", { cache: "no-cache" })
  .then((r) => (r.ok ? r.json() : null))
  .then((data) => {
    if (!data) return;
    RECAP_INDEX = data;
    if (currentView() === "recap") renderRecap();
  })
  .catch(() => {});

// Apply the initial view based on the URL hash (or default to home).
applyView();
