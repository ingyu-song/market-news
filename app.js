"use strict";

const board = document.getElementById("board");
const statusEl = document.getElementById("status");
const filterEl = document.getElementById("filter");
const themeToggle = document.getElementById("theme-toggle");

let DATA = null;

/* ---------- Theme ---------- */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  themeToggle.textContent = theme === "dark" ? "☀️" : "🌙";
  try { localStorage.setItem("mn-theme", theme); } catch (e) {}
}
(function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("mn-theme"); } catch (e) {}
  const prefersDark = window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (prefersDark ? "dark" : "light"));
})();
themeToggle.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme");
  applyTheme(current === "dark" ? "light" : "dark");
});

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

  const list = el("ul", "news-list");
  let shown = 0;
  for (const item of source.items) {
    if (query && !item.title.toLowerCase().includes(query)) continue;
    const li = el("li", "news-item");
    const a = el("a", "news-link");
    a.href = item.link;
    a.target = "_blank";
    a.rel = "noopener";
    a.appendChild(el("span", "news-title", item.title));
    a.appendChild(el("span", "news-time", relativeTime(item.ts)));
    li.appendChild(a);
    list.appendChild(li);
    shown++;
  }

  if (shown === 0) return null; // hide sources with no matching headlines
  group.appendChild(list);
  return group;
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
fetch("data/news.json", { cache: "no-cache" })
  .then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  })
  .then((data) => {
    DATA = data;
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
