#!/usr/bin/env python3
"""Render every Markdown file in the repo to a standalone HTML page.

Output goes to docs_html/, mirroring the source directory layout, plus a
generated docs_html/index.html linking to every page.
"""

import pathlib

from markdown_it import MarkdownIt

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "docs_html"

EXCLUDE_DIRS = {".venv", ".git", "docs_html", "__pycache__"}

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<nav><a href="{index_href}">&larr; All docs</a></nav>
<main>
{body}
</main>
</body>
</html>
"""

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Python Debugging Dojo - Docs</title>
<style>{css}</style>
</head>
<body>
<main>
<h1>Python Debugging Dojo - Docs</h1>
{body}
</main>
</body>
</html>
"""

CSS = """
body {
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    line-height: 1.6;
    color: #24292f;
    max-width: 860px;
    margin: 0 auto;
    padding: 1.5rem 2rem 4rem;
}
nav { margin-bottom: 1.5rem; font-size: 0.9rem; }
nav a { color: #0969da; text-decoration: none; }
nav a:hover { text-decoration: underline; }
h1, h2, h3, h4 { line-height: 1.25; }
code, pre {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: #f6f8fa;
    border-radius: 6px;
}
code { padding: 0.15em 0.4em; font-size: 0.9em; }
pre { padding: 1em; overflow-x: auto; }
pre code { background: none; padding: 0; }
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
}
th, td {
    border: 1px solid #d0d7de;
    padding: 0.5em 0.8em;
    text-align: left;
}
th { background: #f6f8fa; }
blockquote {
    border-left: 4px solid #d0d7de;
    margin: 0;
    padding-left: 1em;
    color: #57606a;
}
a { color: #0969da; }
ul.docs-list { list-style: none; padding-left: 0; }
ul.docs-list li { margin: 0.3em 0; }
ul.docs-list .dir { font-weight: 600; margin-top: 1em; }
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


def build():
    md = MarkdownIt("gfm-like")
    pages = []

    for src in find_markdown_files():
        rel = src.relative_to(ROOT)
        out_rel = rel.with_suffix(".html")
        out_path = OUTPUT_DIR / out_rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        body = render_markdown(md, src.read_text(encoding="utf-8"))
        depth = len(out_rel.parts) - 1
        index_href = "../" * depth + "index.html"

        out_path.write_text(
            PAGE_TEMPLATE.format(
                title=rel.as_posix(), css=CSS, body=body, index_href=index_href
            ),
            encoding="utf-8",
        )
        pages.append(out_rel)

    write_index(pages)


def write_index(pages):
    items = []
    last_dir = None
    for out_rel in sorted(pages, key=lambda p: p.parts):
        parts = out_rel.parts
        current_dir = parts[0] if len(parts) > 1 else ""
        if current_dir != last_dir and current_dir:
            items.append(f'<li class="dir">{current_dir}</li>')
            last_dir = current_dir
        elif len(parts) == 1:
            last_dir = ""
        items.append(
            f'<li><a href="{out_rel.as_posix()}">{out_rel.as_posix()}</a></li>'
        )

    body = "<ul class=\"docs-list\">\n" + "\n".join(items) + "\n</ul>"
    (OUTPUT_DIR / "index.html").write_text(
        INDEX_TEMPLATE.format(css=CSS, body=body), encoding="utf-8"
    )


if __name__ == "__main__":
    build()
    print(f"Docs written to {OUTPUT_DIR.relative_to(ROOT)}/index.html")
