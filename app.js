"use strict";

const board = document.getElementById("board");
const xsumEl = document.getElementById("x-summary");
const highlightsEl = document.getElementById("highlights");
const statusEl = document.getElementById("status");
const filterEl = document.getElementById("filter");

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

function renderXTheme(theme, primary) {
  const card = el("div", primary ? "xsum-card" : "xsum-card xsum-card-sm");
  card.appendChild(el("div", "xsum-topic", theme.topic));
  if (theme.summary) card.appendChild(el("p", "xsum-text", theme.summary));
  if (theme.mentions && theme.mentions.length) {
    const mentions = el("div", "xsum-mentions");
    theme.mentions.slice(0, 8).forEach((h) => {
      const handle = h.startsWith("@") ? h : "@" + h;
      const a = el("a", "xsum-handle", handle);
      a.href = "https://x.com/" + handle.replace(/^@/, "");
      a.target = "_blank";
      a.rel = "noopener";
      mentions.appendChild(a);
    });
    card.appendChild(mentions);
  }
  return card;
}

function renderXSummary(data) {
  xsumEl.innerHTML = "";
  if (!data || !Array.isArray(data.top_3) || data.top_3.length === 0) return;

  const head = el("div", "xsum-head");
  head.appendChild(el("span", "xsum-title", "What X is talking about"));
  const sub = [];
  if (data.account_count) sub.push(`${data.account_count} accounts`);
  if (data.generated_at) sub.push("updated " + formatUpdated(data.generated_at));
  head.appendChild(el("span", "xsum-sub", sub.join(" · ")));
  xsumEl.appendChild(head);

  const grid = el("div", "xsum-grid");
  data.top_3.forEach((t) => grid.appendChild(renderXTheme(t, true)));
  xsumEl.appendChild(grid);

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

/* ---------- Load ---------- */
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
    render();
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
