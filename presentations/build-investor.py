#!/usr/bin/env python3
"""
Build standalone HTML presentations for investor portal.
Creates self-contained reveal.js presentations from markdown.
"""

import os
import re

os.chdir(os.path.dirname(os.path.abspath(__file__)))

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
    ('.tmp-stories.md', 'stories.html', 'User Stories'),
]

if __name__ == "__main__":
    print("Building investor portal presentations...")
    for md, html, title in PRESENTATIONS:
        if os.path.exists(md):
            build_presentation(md, html, title)
        else:
            print(f"  Skipping {md} (not found)")
    print("Done.")
