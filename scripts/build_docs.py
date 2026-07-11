#!/usr/bin/env python3
"""Render every Markdown file in the repo to a standalone HTML page.

Output goes to docs_html/, mirroring the source directory layout, plus a
generated docs_html/index.html linking to every page.

The output is a self-contained (no external requests) documentation site with a
light/dark theme, an auto-generated on-page table of contents, IDE-style code
blocks with copy buttons, and GitHub-compatible heading anchors so in-page
`#slug` links resolve.
"""

import html
import pathlib
import re

from markdown_it import MarkdownIt

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "docs_html"

EXCLUDE_DIRS = {".venv", ".git", "docs_html", "__pycache__"}

SITE_NAME = "Python Debugging Dojo"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<header class="topbar">
  <a class="brand" href="{index_href}"><span class="brand-mark">&#129504;</span> {site}</a>
  <div class="topbar-actions">
    <a class="topbar-link" href="{index_href}">All docs</a>
    <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Toggle theme">&#9789;</button>
  </div>
</header>
<div class="layout">
  <aside class="toc" id="toc" aria-label="On this page"></aside>
  <main class="content" id="content">
{body}
  </main>
</div>
<footer class="site-footer">Rendered from Markdown &middot; {site}</footer>
<script>{js}</script>
</body>
</html>
"""

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{site} &middot; Docs</title>
<style>{css}</style>
</head>
<body>
<header class="topbar">
  <a class="brand" href="index.html"><span class="brand-mark">&#129504;</span> {site}</a>
  <div class="topbar-actions">
    <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Toggle theme">&#9789;</button>
  </div>
</header>
<main class="content home">
<section class="hero">
  <h1>{site}</h1>
  <p class="hero-sub">Hands-on docs for stack dumps, CPU &amp; memory profiling,
  concurrency debugging, and production playbooks &mdash; plus the complete
  <strong>Memory Management Guide</strong>.</p>
  <input id="doc-filter" class="doc-filter" type="search" placeholder="Filter pages&hellip;" autocomplete="off">
</section>
{body}
</main>
<footer class="site-footer">Rendered from Markdown &middot; {site}</footer>
<script>{js}</script>
</body>
</html>
"""

CSS = """
:root {
  --bg: #ffffff;
  --bg-soft: #f7f8fa;
  --surface: #ffffff;
  --surface-2: #f0f2f5;
  --text: #1f2328;
  --muted: #5b6472;
  --border: #e2e6eb;
  --accent: #6366f1;
  --accent-soft: rgba(99, 102, 241, 0.12);
  --accent-2: #0ea5e9;
  --code-bg: #1e293b;
  --code-text: #e2e8f0;
  --shadow: 0 1px 2px rgba(16,24,40,.06), 0 8px 24px rgba(16,24,40,.06);
  --radius: 12px;
  --maxw: 860px;
}
:root[data-theme="dark"] {
  --bg: #0b0f17;
  --bg-soft: #0e131d;
  --surface: #121826;
  --surface-2: #182031;
  --text: #e6edf3;
  --muted: #9aa4b2;
  --border: #253044;
  --accent: #8b93ff;
  --accent-soft: rgba(139, 147, 255, 0.16);
  --accent-2: #38bdf8;
  --code-bg: #0d1424;
  --code-text: #e2e8f0;
  --shadow: 0 1px 2px rgba(0,0,0,.4), 0 12px 32px rgba(0,0,0,.35);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 84px; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 17px;
  line-height: 1.7;
  color: var(--text);
  background: var(--bg-soft);
  -webkit-font-smoothing: antialiased;
}

/* ---------- Top bar ---------- */
.topbar {
  position: sticky; top: 0; z-index: 50;
  display: flex; align-items: center; justify-content: space-between;
  gap: 1rem;
  padding: 0.7rem 1.4rem;
  background: color-mix(in srgb, var(--bg) 82%, transparent);
  backdrop-filter: saturate(180%) blur(10px);
  border-bottom: 1px solid var(--border);
}
.brand { display: inline-flex; align-items: center; gap: .55rem;
  font-weight: 700; letter-spacing: -.01em; color: var(--text); text-decoration: none; }
.brand-mark { font-size: 1.15rem; }
.topbar-actions { display: flex; align-items: center; gap: .4rem; }
.topbar-link { color: var(--muted); text-decoration: none; font-size: .92rem;
  padding: .35rem .6rem; border-radius: 8px; }
.topbar-link:hover { color: var(--text); background: var(--surface-2); }
.theme-toggle {
  cursor: pointer; border: 1px solid var(--border); background: var(--surface);
  color: var(--text); width: 36px; height: 36px; border-radius: 9px;
  font-size: 1rem; line-height: 1; display: grid; place-items: center;
  transition: transform .15s ease, background .15s ease;
}
.theme-toggle:hover { background: var(--surface-2); transform: translateY(-1px); }

/* ---------- Layout ---------- */
.layout { display: grid; grid-template-columns: 1fr minmax(0, var(--maxw)) 1fr;
  gap: 1.5rem; align-items: start; }
.content {
  grid-column: 2;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 2.4rem clamp(1.1rem, 4vw, 3rem) 3rem;
  margin: 1.6rem 1rem;
  overflow-wrap: break-word;
}
.toc {
  grid-column: 3;
  position: sticky; top: 84px;
  align-self: start;
  max-height: calc(100vh - 100px); overflow-y: auto;
  margin: 1.6rem 1rem 1.6rem 0;
  padding: .4rem .2rem .4rem 1rem;
  border-left: 1px solid var(--border);
  font-size: .86rem;
}
.toc:empty { display: none; }
.toc h4 { margin: .2rem 0 .6rem; font-size: .72rem; text-transform: uppercase;
  letter-spacing: .08em; color: var(--muted); }
.toc a { display: block; color: var(--muted); text-decoration: none;
  padding: .18rem 0; border-left: 2px solid transparent; margin-left: -1rem;
  padding-left: 1rem; transition: color .12s ease, border-color .12s ease; }
.toc a:hover { color: var(--text); }
.toc a.h3 { padding-left: 1.9rem; font-size: .82rem; }
.toc a.active { color: var(--accent); border-left-color: var(--accent); font-weight: 600; }

@media (max-width: 1180px) {
  .layout { grid-template-columns: 1fr; }
  .content { grid-column: 1; max-width: var(--maxw); margin: 1.4rem auto; }
  .toc { display: none; }
}

/* ---------- Typography ---------- */
.content h1, .content h2, .content h3, .content h4 {
  line-height: 1.25; letter-spacing: -.015em; scroll-margin-top: 84px;
  position: relative;
}
.content h1 { font-size: 2.1rem; margin: .2rem 0 1.2rem; padding-bottom: .5rem;
  border-bottom: 1px solid var(--border); }
.content h2 { font-size: 1.5rem; margin: 2.4rem 0 1rem; padding-top: .4rem; }
.content h3 { font-size: 1.2rem; margin: 1.8rem 0 .7rem; }
.content h4 { font-size: 1.02rem; margin: 1.4rem 0 .6rem; color: var(--muted); }
.content h2::before { content: ""; position: absolute; left: -1rem; top: .95rem;
  width: 5px; height: 1.05rem; border-radius: 3px; background: var(--accent);
  opacity: .0; transition: opacity .15s; }
.content h2:hover::before { opacity: 1; }
.anchor { position: absolute; left: -1.3rem; opacity: 0; text-decoration: none;
  color: var(--muted); font-weight: 400; }
.content h1:hover .anchor, .content h2:hover .anchor,
.content h3:hover .anchor, .content h4:hover .anchor { opacity: .7; }
.content p { margin: .9rem 0; }
.content a { color: var(--accent); text-decoration: none;
  border-bottom: 1px solid transparent; }
.content a:hover { border-bottom-color: var(--accent); }
.content hr { border: none; border-top: 1px solid var(--border); margin: 2.2rem 0; }
.content ul, .content ol { padding-left: 1.4rem; }
.content li { margin: .3rem 0; }
.content li::marker { color: var(--accent); }
strong { font-weight: 700; }

/* ---------- Code ---------- */
code, pre, .codewrap {
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
}
.content :not(pre) > code {
  background: var(--accent-soft); color: var(--text);
  padding: .12em .4em; border-radius: 6px; font-size: .86em;
  border: 1px solid color-mix(in srgb, var(--accent) 22%, transparent);
}
.codewrap { position: relative; margin: 1.3rem 0;
  border-radius: 10px; overflow: hidden; box-shadow: var(--shadow);
  border: 1px solid rgba(0,0,0,.35); }
.codewrap .lang-badge {
  position: absolute; top: 0; left: 0;
  font-size: .68rem; letter-spacing: .06em; text-transform: uppercase;
  color: #9fb0c7; background: rgba(255,255,255,.05);
  padding: .25rem .6rem; border-bottom-right-radius: 8px; user-select: none;
}
.codewrap .copy-btn {
  position: absolute; top: .4rem; right: .4rem;
  font-size: .72rem; color: #cbd5e1; cursor: pointer;
  background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.14);
  padding: .28rem .55rem; border-radius: 7px; transition: background .15s, color .15s;
}
.codewrap .copy-btn:hover { background: rgba(255,255,255,.18); color: #fff; }
.codewrap .copy-btn.copied { color: #86efac; border-color: #86efac55; }
pre { margin: 0; background: var(--code-bg); color: var(--code-text);
  padding: 1.5rem 1.1rem 1.1rem; overflow-x: auto; font-size: .86rem; line-height: 1.6; }
pre code { background: none; padding: 0; border: none; color: inherit; font-size: inherit; }

/* ---------- Tables ---------- */
.content table { border-collapse: collapse; display: block; width: max-content;
  max-width: 100%; overflow-x: auto; margin: 1.3rem 0; font-size: .93rem;
  border: 1px solid var(--border); border-radius: 10px; }
.content th, .content td { border-bottom: 1px solid var(--border);
  border-right: 1px solid var(--border); padding: .55rem .85rem; text-align: left; }
.content tr td:last-child, .content tr th:last-child { border-right: none; }
.content thead th { background: var(--surface-2); font-weight: 700;
  position: sticky; top: 0; }
.content tbody tr:nth-child(even) { background: color-mix(in srgb, var(--surface-2) 55%, transparent); }
.content tbody tr:hover { background: var(--accent-soft); }
.content tbody tr:last-child td { border-bottom: none; }

/* ---------- Blockquote callouts ---------- */
.content blockquote {
  margin: 1.3rem 0; padding: .9rem 1.1rem; color: var(--text);
  background: var(--accent-soft);
  border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
  border-left: 4px solid var(--accent); border-radius: 10px;
}
.content blockquote p { margin: .4rem 0; }
.content blockquote strong:first-child { color: var(--accent); }

/* ---------- Images ---------- */
.content img { max-width: 100%; border-radius: 8px; }

/* ---------- Home / index ---------- */
.home { max-width: 1080px; margin: 0 auto; padding: 1rem 1.2rem 3rem; }
.hero { padding: 2.4rem 0 1.4rem; }
.hero h1 { font-size: 2.4rem; margin: 0 0 .5rem; letter-spacing: -.02em; }
.hero-sub { color: var(--muted); font-size: 1.05rem; max-width: 60ch; margin: 0 0 1.3rem; }
.doc-filter { width: 100%; max-width: 420px; padding: .7rem .9rem;
  border: 1px solid var(--border); border-radius: 10px; background: var(--surface);
  color: var(--text); font-size: .95rem; }
.doc-filter:focus { outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft); }
.section-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1.1rem; margin-top: 1.4rem; }
.card { background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); padding: 1.2rem 1.3rem;
  transition: transform .15s ease, border-color .15s ease; }
.card:hover { transform: translateY(-2px); border-color: var(--accent); }
.card h3 { margin: 0 0 .2rem; font-size: 1.05rem; letter-spacing: -.01em;
  display: flex; align-items: center; gap: .5rem; }
.card .card-badge { font-size: .68rem; text-transform: uppercase; letter-spacing: .06em;
  color: var(--accent); background: var(--accent-soft); padding: .12rem .5rem;
  border-radius: 999px; }
.card ul { list-style: none; padding: 0; margin: .6rem 0 0; }
.card li { margin: .12rem 0; }
.card a { color: var(--text); text-decoration: none; display: block;
  padding: .25rem .45rem; border-radius: 7px; font-size: .92rem; }
.card a:hover { background: var(--accent-soft); color: var(--accent); }
.card a .fname { color: var(--muted); font-size: .82em; }
.card.hidden, .card li.hidden { display: none; }

.site-footer { text-align: center; color: var(--muted); font-size: .82rem;
  padding: 2rem 1rem 3rem; }

::selection { background: var(--accent-soft); }
"""

JS = """
(function () {
  var root = document.documentElement;
  // --- Theme ---
  var stored = null;
  try { stored = localStorage.getItem('ddojo-theme'); } catch (e) {}
  var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var theme = stored || (prefersDark ? 'dark' : 'light');
  applyTheme(theme);
  function applyTheme(t) {
    root.setAttribute('data-theme', t);
    var btn = document.getElementById('theme-toggle');
    if (btn) btn.innerHTML = (t === 'dark') ? '\\u2600' : '\\u263D';
  }
  var toggle = document.getElementById('theme-toggle');
  if (toggle) toggle.addEventListener('click', function () {
    theme = (root.getAttribute('data-theme') === 'dark') ? 'light' : 'dark';
    applyTheme(theme);
    try { localStorage.setItem('ddojo-theme', theme); } catch (e) {}
  });

  var content = document.getElementById('content');

  // --- Anchor links on headings ---
  if (content) {
    content.querySelectorAll('h1[id], h2[id], h3[id], h4[id]').forEach(function (h) {
      var a = document.createElement('a');
      a.className = 'anchor'; a.href = '#' + h.id; a.textContent = '#';
      a.setAttribute('aria-hidden', 'true');
      h.insertBefore(a, h.firstChild);
    });
  }

  // --- Build on-page TOC from h2/h3 ---
  var toc = document.getElementById('toc');
  if (toc && content) {
    var heads = content.querySelectorAll('h2[id], h3[id]');
    if (heads.length > 2) {
      var html = '<h4>On this page</h4>';
      heads.forEach(function (h) {
        var lvl = h.tagName.toLowerCase();
        var text = h.textContent.replace(/^#/, '').trim();
        html += '<a class="' + lvl + '" href="#' + h.id + '">' + escapeHtml(text) + '</a>';
      });
      toc.innerHTML = html;

      // Scroll-spy
      var links = {};
      toc.querySelectorAll('a').forEach(function (a) {
        links[a.getAttribute('href').slice(1)] = a;
      });
      var spy = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            Object.values(links).forEach(function (l) { l.classList.remove('active'); });
            var active = links[en.target.id];
            if (active) active.classList.add('active');
          }
        });
      }, { rootMargin: '-80px 0px -70% 0px' });
      heads.forEach(function (h) { spy.observe(h); });
    }
  }

  // --- Wrap code blocks: language badge + copy button ---
  if (content) {
    content.querySelectorAll('pre').forEach(function (pre) {
      var wrap = document.createElement('div');
      wrap.className = 'codewrap';
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);

      var code = pre.querySelector('code');
      var lang = '';
      if (code) {
        (code.className || '').split(/\\s+/).forEach(function (c) {
          if (c.indexOf('language-') === 0) lang = c.slice(9);
        });
      }
      if (lang) {
        var badge = document.createElement('span');
        badge.className = 'lang-badge'; badge.textContent = lang;
        wrap.appendChild(badge);
      }
      var btn = document.createElement('button');
      btn.className = 'copy-btn'; btn.type = 'button'; btn.textContent = 'Copy';
      btn.addEventListener('click', function () {
        var text = (code || pre).innerText;
        navigator.clipboard.writeText(text).then(function () {
          btn.textContent = 'Copied'; btn.classList.add('copied');
          setTimeout(function () { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 1400);
        });
      });
      wrap.appendChild(btn);
    });
  }

  // --- Home page filter ---
  var filter = document.getElementById('doc-filter');
  if (filter) {
    filter.addEventListener('input', function () {
      var q = filter.value.toLowerCase();
      document.querySelectorAll('.card').forEach(function (card) {
        var anyVisible = false;
        card.querySelectorAll('li').forEach(function (li) {
          var match = li.textContent.toLowerCase().indexOf(q) !== -1;
          li.classList.toggle('hidden', !match);
          if (match) anyVisible = true;
        });
        card.classList.toggle('hidden', !anyVisible);
      });
    });
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
})();
"""


def find_markdown_files():
    for path in sorted(ROOT.rglob("*.md")):
        rel_parts = path.relative_to(ROOT).parts
        if any(part in EXCLUDE_DIRS for part in rel_parts):
            continue
        yield path


def render_markdown(md, text):
    def link_open(self, tokens, idx, options, env):
        token = tokens[idx]
        href = token.attrGet("href")
        if href and not href.startswith(("http://", "https://", "#")):
            base, _, anchor = href.partition("#")
            if base.endswith(".md"):
                new_href = base[:-3] + ".html"
                if anchor:
                    new_href += "#" + anchor
                token.attrSet("href", new_href)
        return self.renderToken(tokens, idx, options, env)

    md.add_render_rule("link_open", link_open)
    return md.render(text)


def slugify(text):
    """GitHub-compatible heading slug so in-page `#anchor` links resolve."""
    slug = text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)   # drop punctuation (keeps unicode word chars)
    slug = re.sub(r"\s", "-", slug)         # spaces -> hyphens (repeats preserved)
    return slug


def add_heading_ids(rendered):
    """Inject unique, GitHub-style id attributes into <h1>..<h6> tags."""
    seen = {}

    def repl(match):
        level, attrs, inner = match.group(1), match.group(2), match.group(3)
        text = re.sub(r"<[^>]+>", "", inner)          # strip inline tags
        text = html.unescape(text)
        base = slugify(text)
        if not base:
            base = "section"
        slug = base
        if slug in seen:
            seen[slug] += 1
            slug = f"{base}-{seen[base]}"
        else:
            seen[slug] = 0
        if "id=" in attrs:
            return match.group(0)
        return f"<h{level}{attrs} id=\"{slug}\">{inner}</h{level}>"

    return re.sub(r"<h([1-6])([^>]*)>(.*?)</h\1>", repl, rendered, flags=re.DOTALL)


def extract_title(text, fallback):
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return re.sub(r"[`*_]", "", line[2:].strip())
    return fallback


def prettify(name):
    name = re.sub(r"^\d+[_-]", "", name)
    return name.replace("_", " ").replace("-", " ").strip().title()


def build():
    md = MarkdownIt("gfm-like")
    pages = []  # (out_rel, title)

    for src in find_markdown_files():
        rel = src.relative_to(ROOT)
        out_rel = rel.with_suffix(".html")
        out_path = OUTPUT_DIR / out_rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        text = src.read_text(encoding="utf-8")
        body = add_heading_ids(render_markdown(md, text))
        title = extract_title(text, rel.as_posix())
        depth = len(out_rel.parts) - 1
        index_href = "../" * depth + "index.html"

        out_path.write_text(
            PAGE_TEMPLATE.format(
                title=html.escape(title), css=CSS, js=JS, body=body,
                index_href=index_href, site=SITE_NAME,
            ),
            encoding="utf-8",
        )
        pages.append((out_rel, title))

    write_index(pages)


def write_index(pages):
    groups = {}  # section directory (posix) -> list of (out_rel, title)
    for out_rel, title in pages:
        parent = out_rel.parent.as_posix()
        key = "" if parent == "." else parent
        groups.setdefault(key, []).append((out_rel, title))

    def group_sort_key(k):
        return (k == "", k)  # top-level ("") last

    cards = []
    for key in sorted(groups, key=group_sort_key):
        entries = sorted(groups[key], key=lambda p: p[0].parts)
        heading = "Top level" if key == "" else prettify(key.split("/")[-1])
        badge = str(len(entries))
        items = []
        for out_rel, title in entries:
            fname = out_rel.name
            items.append(
                f'      <li><a href="{out_rel.as_posix()}">{html.escape(title)}'
                f' <span class="fname">{html.escape(fname)}</span></a></li>'
            )
        cards.append(
            '  <div class="card">\n'
            f'    <h3>{html.escape(heading)} <span class="card-badge">{badge}</span></h3>\n'
            '    <ul>\n' + "\n".join(items) + "\n    </ul>\n  </div>"
        )

    body = '<div class="section-grid">\n' + "\n".join(cards) + "\n</div>"
    (OUTPUT_DIR / "index.html").write_text(
        INDEX_TEMPLATE.format(css=CSS, js=JS, body=body, site=SITE_NAME),
        encoding="utf-8",
    )


if __name__ == "__main__":
    build()
    print(f"Docs written to {OUTPUT_DIR.relative_to(ROOT)}/index.html")
