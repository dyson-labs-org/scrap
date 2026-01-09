#!/usr/bin/env python3
"""
Build standalone HTML presentations for investor portal.
Creates self-contained reveal.js presentations from markdown.
"""

import os
import re
import glob

os.chdir(os.path.dirname(os.path.abspath(__file__)))

INDEX_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dyson Labs - Investor Portal</title>
    <style>
        :root {
            --bg: #0d1117;
            --card-bg: #161b22;
            --border: #30363d;
            --text: #e6edf3;
            --muted: #8b949e;
            --accent: #58a6ff;
            --green: #3fb950;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 2rem;
        }
        .container { max-width: 900px; margin: 0 auto; }
        header {
            text-align: center;
            padding: 3rem 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 3rem;
        }
        h1 { color: var(--accent); font-size: 2.5rem; margin-bottom: 0.5rem; }
        .tagline { color: var(--muted); font-size: 1.1rem; }
        .section { margin-bottom: 3rem; }
        h2 { color: var(--accent); font-size: 1.3rem; margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.5rem;
            text-decoration: none;
            color: var(--text);
            transition: border-color 0.2s, transform 0.2s;
        }
        .card:hover { border-color: var(--accent); transform: translateY(-2px); }
        .card h3 { color: var(--accent); margin-bottom: 0.5rem; }
        .card p { color: var(--muted); font-size: 0.9rem; line-height: 1.5; }
        .card .badge {
            display: inline-block;
            background: var(--accent);
            color: var(--bg);
            font-size: 0.7rem;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            margin-top: 0.75rem;
            font-weight: 600;
        }
        .card .badge.recommended { background: var(--green); }
        footer {
            text-align: center;
            padding: 2rem;
            color: var(--muted);
            font-size: 0.85rem;
            border-top: 1px solid var(--border);
            margin-top: 2rem;
        }
        .nav-hint {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 2rem;
            font-size: 0.9rem;
            color: var(--muted);
        }
        .nav-hint code {
            background: var(--bg);
            padding: 0.2rem 0.4rem;
            border-radius: 4px;
            color: var(--text);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Dyson Labs</h1>
            <p class="tagline">SCRAP: Satellite Capability and Authorization Protocol</p>
        </header>
        <div class="nav-hint">
            <strong>Presentation Controls:</strong> Use <code>→</code> / <code>←</code> to navigate slides,
            <code>Esc</code> for overview, <code>F</code> for fullscreen
        </div>
        <div class="section">
            <h2>Presentations by Audience</h2>
            <div class="grid">
                <a href="commercial.html" class="card">
                    <h3>Commercial / Investor</h3>
                    <p>Business model, market opportunity, and investment thesis for SCRAP.</p>
                    <span class="badge recommended">Recommended</span>
                </a>
                <a href="cofounder.html" class="card">
                    <h3>Co-Founder Opportunity</h3>
                    <p>Join as business/operations co-founder. SDVOSB strategic priority.</p>
                    <span class="badge" style="background: #f85149;">Recruiting</span>
                </a>
                <a href="nasa.html" class="card">
                    <h3>NASA</h3>
                    <p>CCSDS alignment, technology readiness levels, and integration path.</p>
                    <span class="badge">Government</span>
                </a>
                <a href="darpa.html" class="card">
                    <h3>DARPA</h3>
                    <p>Contested environment operations and defense applications.</p>
                    <span class="badge">Government</span>
                </a>
            </div>
        </div>
        <div class="section">
            <h2>Documentation</h2>
            <div class="grid">
                <a href="/docs/" class="card">
                    <h3>Protocol Specifications</h3>
                    <p>SCRAP, SISL, HTLC/PTLC specs, strategy docs, and research.</p>
                    <span class="badge">Reference</span>
                </a>
            </div>
        </div>
        <div class="section">
            <h2>User Stories</h2>
            <p style="color: var(--muted); margin-bottom: 1rem;">Real-world scenarios demonstrating SCRAP capabilities</p>
            <div class="grid">
                <a href="stories.html" class="card">
                    <h3>All Stories (Slideshow)</h3>
                    <p>Browse all user stories as a presentation</p>
                    <span class="badge recommended">Start Here</span>
                </a>
            </div>
            <div class="grid" style="margin-top: 1rem; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));">
{story_links}
            </div>
        </div>
        <footer>
            <p>Confidential - Dyson Labs</p>
        </footer>
    </div>
</body>
</html>
'''

TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Dyson Labs</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reset.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/black.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/highlight/monokai.css">
    <style>
{theme_css}
    </style>
</head>
<body>
    <div class="reveal">
        <div class="slides">
{slides_html}
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/markdown/markdown.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/highlight/highlight.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
{mermaid_init}
    </script>
    <script>
        Reveal.initialize({{
            hash: true,
            plugins: [ RevealMarkdown, RevealHighlight ]
        }});
    </script>
</body>
</html>
'''

def load_file(path):
    with open(path, 'r') as f:
        return f.read()

def markdown_to_html_slides(md_content):
    slides = re.split(r'\n---\n', md_content)
    html_parts = []
    for slide in slides:
        slide = slide.strip()
        if not slide:
            continue
        escaped = slide.replace('`', '\\`').replace('$', '\\$')
        html_parts.append(f'            <section data-markdown><textarea data-template>\n{slide}\n            </textarea></section>')
    return '\n'.join(html_parts)

def build_presentation(md_file, output_file, title):
    md_content = load_file(md_file)
    theme_css = load_file('_theme.css')
    mermaid_init = load_file('mermaid-init.js')

    slides_html = markdown_to_html_slides(md_content)

    html = TEMPLATE.format(
        title=title,
        theme_css=theme_css,
        slides_html=slides_html,
        mermaid_init=mermaid_init
    )

    with open(output_file, 'w') as f:
        f.write(html)
    print(f"  Built: {output_file}")

PRESENTATIONS = [
    ('.tmp-nasa.md', 'nasa.html', 'NASA Presentation'),
    ('.tmp-darpa.md', 'darpa.html', 'DARPA Presentation'),
    ('.tmp-commercial.md', 'commercial.html', 'Commercial/Investor Presentation'),
    ('.tmp-cofounder.md', 'cofounder.html', 'Co-Founder Opportunity'),
    ('.tmp-stories.md', 'stories.html', 'User Stories'),
]

def extract_story_title(filepath):
    """Extract title from story markdown (first ## heading)"""
    with open(filepath) as f:
        for line in f:
            if line.startswith('## '):
                return line[3:].strip()
    # Fallback to filename
    name = os.path.basename(filepath).replace('.md', '').replace('_', ' ')
    return name.title()

def build_stories_md():
    """Concatenate all stories/*.md into .tmp-stories.md, return list of (title, index)"""
    story_files = sorted(glob.glob('stories/*.md'))
    if not story_files:
        return []
    stories = []
    with open('.tmp-stories.md', 'w') as out:
        for i, sf in enumerate(story_files):
            title = extract_story_title(sf)
            stories.append((title, i))
            with open(sf) as f:
                out.write(f.read())
            out.write('\n\n---\n\n')
    return stories

def generate_story_links(stories):
    """Generate HTML links for each story"""
    links = []
    for title, idx in stories:
        links.append(f'''                <a href="stories.html#/{idx}" class="card" style="padding: 1rem;">
                    <h3 style="font-size: 0.95rem;">{title}</h3>
                </a>''')
    return '\n'.join(links)

if __name__ == "__main__":
    print("Building investor portal presentations...")

    # Build stories markdown and get list of stories
    stories = build_stories_md()
    if stories:
        print(f"  Assembled {len(stories)} stories from stories/*.md")

    # Build presentation HTML files
    for md, html, title in PRESENTATIONS:
        if os.path.exists(md):
            build_presentation(md, html, title)
        else:
            print(f"  Skipping {md} (not found)")

    # Write index.html with story links
    story_links = generate_story_links(stories) if stories else ""
    index_html = INDEX_HTML.replace('{story_links}', story_links)
    with open('index.html', 'w') as f:
        f.write(index_html)
    print("  Built: index.html")

    print("Done.")
