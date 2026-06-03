#!/usr/bin/env python3
"""
China Travel Journal Builder

Converts Obsidian markdown with embedded photos/videos into:
- PDF (for Signal sharing)
- HTML (with video support)

Usage: python3 build-journal.py
"""

import os
import re
from pathlib import Path
from datetime import datetime
import markdown
from jinja2 import Template

# Configuration
PHOTOS_FOLDER = Path("/home/bruce/Documents/Projects/China2026")
OBSIDIAN_FILE = Path("/home/bruce/Documents/global/China Trip Review.md")
OUTPUT_FOLDER = PHOTOS_FOLDER
TEMPLATE_FILE = Path("/home/bruce/Documents/Projects/journal-template.html")

# Auto-select ~1 photo per day to keep PDF under Signal's 100MB limit
MAX_PHOTOS_PER_DAY = 3


def scan_media_files():
    """Scan photos folder and index all media files by date."""
    media = {
        'photos': [],
        'videos': []
    }

    for f in PHOTOS_FOLDER.iterdir():
        if f.suffix.lower() in ['.jpg', '.jpeg', '.png']:
            # Extract date from filename like IMG_20260513_173732_545.jpg
            match = re.search(r'IMG_(\d{4})(\d{2})(\d{2})_(\d{6})', f.name)
            if match:
                year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                date_str = f"{year}-{month:02d}-{day:02d}"
                media['photos'].append({
                    'path': str(f),
                    'name': f.name,
                    'date': date_str,
                    'timestamp': f"{year}-{month:02d}-{day:02d} {match.group(4)[:2]}:{match.group(4)[2:4]}"
                })
        elif f.suffix.lower() == '.mp4':
            match = re.search(r'VID_(\d{4})(\d{2})(\d{2})_(\d{6})', f.name)
            if match:
                year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                date_str = f"{year}-{month:02d}-{day:02d}"
                media['videos'].append({
                    'path': str(f),
                    'name': f.name,
                    'date': date_str
                })

    # Sort by date
    media['photos'].sort(key=lambda x: x['date'])
    media['videos'].sort(key=lambda x: x['date'])

    return media


def parse_obsidian_markdown(content, media):
    """Parse Obsidian markdown and convert ![[file]] syntax to HTML."""

    # Build lookup for media files
    photo_lookup = {p['name']: p for p in media['photos']}
    video_lookup = {v['name']: v for v in media['videos']}

    lines = content.split('\n')
    html_lines = []
    current_date = None
    photo_count_today = 0
    last_date = None
    in_list = False

    for line in lines:
        # Check for date headers: ## May 13 - Beijing, # Tuesday May 12, or ## 2026-05-13
        date_match = re.match(r'^(#+)\s*(\w+\s+\w+\s+\d+|\w+\s+\d+|\d{4}-\d{2}-\d{2})\s*-?\s*(.*)', line)
        if date_match:
            date_str = date_match.group(2)
            location = date_match.group(3).strip()
            current_date = date_str
            last_date = date_str
            photo_count_today = 0
            header_html = f'<h2><span class="date-header">{date_str}</span>'
            if location:
                header_html += f" — {location}"
            header_html += '</h2>'
            html_lines.append(header_html)
            continue

        # Handle ![[filename.jpg]] syntax for photos
        photo_match = re.match(r'^!\[\[([^\]]+)\]\](.*)$', line)
        if photo_match:
            filename = photo_match.group(1)
            caption = photo_match.group(2).strip()

            # Find matching photo
            photo = None
            if filename in photo_lookup:
                photo = photo_lookup[filename]
            else:
                # Try fuzzy match
                for p in media['photos']:
                    if filename.lower() in p['name'].lower() or p['name'].startswith(filename[:10]):
                        photo = p
                        break

            if photo:
                # Auto-select: limit photos per day
                if photo['date'] != last_date:
                    photo_count_today = 0
                    last_date = photo['date']

                if photo_count_today < MAX_PHOTOS_PER_DAY:
                    photo_count_today += 1
                    is_full = 'full-width' if photo_count_today == 1 else ''
                    html_lines.append(f'<figure class="photo {is_full}">')
                    html_lines.append(f'<img src="{photo["path"]}" alt="{photo["name"]}">')
                    if caption:
                        html_lines.append(f'<figcaption>{caption.strip("*").strip()}</figcaption>')
                    html_lines.append('</figure>')
            continue

        # Handle ![[video.mp4]] syntax
        video_match = re.match(r'^!\[\[([^\]]+\.(mp4|mov))\]\](.*)$', line)
        if video_match:
            filename = video_match.group(1)
            caption = video_match.group(3).strip()

            video = None
            if filename in video_lookup:
                video = video_lookup[filename]
            else:
                for v in media['videos']:
                    if filename.lower() in v['name'].lower():
                        video = v
                        break

            if video:
                html_lines.append('<div class="video-container">')
                html_lines.append(f'<video controls><source src="{video["path"]}" type="video/mp4">Your browser does not support video.</video>')
                if caption:
                    html_lines.append(f'<p class="video-note">{caption.strip("*").strip()}</p>')
                html_lines.append('</div>')
            continue

        # Regular markdown line - convert to paragraph if it has content
        if line.strip() and not line.startswith('#'):
            # Handle bullet points (*)
            if line.strip().startswith('* '):
                if not in_list:
                    html_lines.append('<ul>')
                    in_list = True
                bullet_content = line.strip()[2:]  # Remove "* "
                html_lines.append(f'<li>{bullet_content}</li>')
            else:
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                html_lines.append(f'<p>{line.strip()}</p>')
        elif line.startswith('# ') and not html_lines:
            # Main title (only if first line)
            title = line[2:].strip()
            html_lines.insert(0, f'<h1>{title}</h1>')

    return '\n'.join(html_lines)


def generate_html(content, media, template_path):
    """Generate HTML from markdown content."""

    with open(template_path, 'r') as f:
        template = Template(f.read())

    html_content = parse_obsidian_markdown(content, media)

    return template.render(
        title="China Trip 2026",
        content=html_content
    )


def convert_to_pdf(html_content, output_path):
    """Convert HTML to PDF using WeasyPrint."""
    from weasyprint import HTML

    html_doc = HTML(string=html_content)
    html_doc.write_pdf(output_path)

    # Check file size
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"PDF generated: {output_path}")
    print(f"File size: {size_mb:.1f} MB")

    if size_mb > 100:
        print(f"WARNING: PDF exceeds Signal's 100MB limit!")
        print(f"Consider reducing MAX_PHOTOS_PER_DAY or splitting into multiple PDFs.")

    return size_mb


def generate_html_version(html_content, output_path):
    """Save HTML version (for video support)."""
    with open(output_path, 'w') as f:
        f.write(html_content)
    print(f"HTML generated: {output_path}")


def main():
    print("=" * 50)
    print("China 2026 Travel Journal Builder")
    print("=" * 50)

    # Check dependencies
    try:
        from weasyprint import HTML
        print("✓ WeasyPrint available")
    except ImportError:
        print("✗ WeasyPrint not installed")
        print("  Run: sudo apt install python3-weasyprint python3-jinja2")
        return

    # Scan media files
    print(f"\nScanning {PHOTOS_FOLDER}...")
    media = scan_media_files()
    print(f"  Found {len(media['photos'])} photos")
    print(f"  Found {len(media['videos'])} videos")

    # Read Obsidian markdown
    if not OBSIDIAN_FILE.exists():
        print(f"\n✗ Obsidian file not found: {OBSIDIAN_FILE}")
        print("  Please create your journal entries first.")
        return

    print(f"\nReading {OBSIDIAN_FILE}...")
    with open(OBSIDIAN_FILE, 'r') as f:
        content = f.read()

    if not content.strip():
        print("  File is empty - add journal entries with ![[photo.jpg]] embeds")
        return

    # Generate HTML
    print("\nGenerating HTML...")
    html_content = generate_html(content, media, TEMPLATE_FILE)

    # Generate outputs
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    pdf_path = OUTPUT_FOLDER / "china-journal.pdf"
    html_path = OUTPUT_FOLDER / "china-journal.html"

    convert_to_pdf(html_content, pdf_path)
    generate_html_version(html_content, html_path)

    print("\n✓ Done! Share via Signal:")
    print(f"  - PDF: {pdf_path} (best for mobile)")
    print(f"  - HTML: {html_path} (includes videos)")


if __name__ == "__main__":
    main()
