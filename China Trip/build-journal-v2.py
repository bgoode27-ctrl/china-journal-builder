#!/usr/bin/env python3
"""
China Travel Journal Builder (Enhanced v2)
Properly parses Obsidian markdown with all formatting, icons, tables, and callouts.
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime
import markdown
from jinja2 import Template
from weasyprint import HTML

# Configuration
PHOTOS_FOLDER = Path("/opt/vault/Research/China/raw/assets/photos/China2026")
JOURNAL_DIR = Path("/opt/vault/Research/China/wiki/journal")
OUTPUT_FOLDER = Path("/opt/projects/China Trip/build")
TEMPLATE_FILE = Path("/opt/projects/journal-template.html")

# Copy media into output folder for relative paths
MEDIA_OUTPUT_DIR = OUTPUT_FOLDER / "assets"

# Files to skip in journal directory
SKIP_FILES = {"Journal Entry Template 3.md"}

# Limit per day
MAX_PHOTOS_PER_DAY = 6


def scan_media_files():
    """Scan photos folder and index all media files by date."""
    media = {
        'photos': [],
        'videos': []
    }

    photo_exts = {'.jpg', '.jpeg', '.png', '.heic', '.HEIC', '.JPG', '.JPEG', '.PNG'}
    video_exts = {'.mp4', '.mov', '.MOV', '.MP4'}

    for f in sorted(PHOTOS_FOLDER.iterdir()):
        ext = f.suffix
        if ext in photo_exts:
            match = re.search(r'(?:IMG_|VID_|img_)(\d{4})(\d{2})(\d{2})_(\d{6})', f.name)
            if not match:
                match = re.search(r'IMG_(\d{4})', f.name)
                if match:
                    year = int(match.group(1))
                    month, day = 5, 13
                else:
                    continue
            if len(match.groups()) >= 3:
                year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                time_part = match.group(4) if len(match.groups()) >= 4 else "000000"
            else:
                year, month, day = int(match.group(1)), 5, 13
                time_part = "000000"
            date_str = f"{year}-{month:02d}-{day:02d}"
            media['photos'].append({
                'path': str(f),
                'name': f.name,
                'date': date_str,
                'rel_path': f"assets/{f.name}",
                'timestamp': f"{year}-{month:02d}-{day:02d} {time_part[:2]}:{time_part[2:4]}"
            })
        elif ext in video_exts:
            match = re.search(r'(?:VID_|IMG_|vid_)(\d{4})(\d{2})(\d{2})_(\d{6})', f.name)
            if not match:
                match = re.search(r'VID_(\d{4})', f.name)
                if match:
                    year = int(match.group(1))
                    month, day = 5, 13
                else:
                    continue
            if len(match.groups()) >= 3:
                year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            else:
                year, month, day = int(match.group(1)), 5, 13
            date_str = f"{year}-{month:02d}-{day:02d}"
            media['videos'].append({
                'path': str(f),
                'name': f.name,
                'date': date_str,
                'rel_path': f"assets/{f.name}"
            })

    media['photos'].sort(key=lambda x: x['date'])
    media['videos'].sort(key=lambda x: x['date'])
    return media


def extract_metadata(content):
    """Extract front matter metadata."""
    metadata = {}
    match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
    if match:
        front_matter = match.group(1)
        for line in front_matter.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                metadata[key.strip()] = value.strip()
    return metadata


def replace_obsidian_images(content, media):
    """Replace ![[filename]] syntax with placeholders before markdown processing."""
    photo_lookup = {p['name']: p for p in media['photos']}
    video_lookup = {v['name']: v for v in media['videos']}

    lines = content.split('\n')
    processed_lines = []
    photo_count_today = 0
    last_date = None

    for line in lines:
        # Handle videos
        video_match = re.match(r'^!\[\[([^\]]+\.(mp4|mov|MP4|MOV))\]\]\s*(.*)$', line)
        if video_match:
            raw_ref = video_match.group(1).strip()
            caption = video_match.group(3).strip()
            filename = Path(raw_ref).name

            video = None
            if filename in video_lookup:
                video = video_lookup[filename]
            else:
                for v in media['videos']:
                    if filename.lower() in v['name'].lower():
                        video = v
                        break

            if video:
                video_html = f'<div class="video-container">'
                video_html += f'<video controls preload="metadata"><source src="{video["rel_path"]}" type="video/mp4">Your browser does not support video.</video>'
                if caption:
                    video_html += f'<p class="video-note">{caption.strip("*").strip()}</p>'
                video_html += '</div>'
                processed_lines.append(video_html)
            continue

        # Handle photos
        photo_match = re.match(r'^!\[\[([^\]]+)\]\]\s*(.*)$', line)
        if photo_match:
            raw_ref = photo_match.group(1).strip()
            caption = photo_match.group(2).strip()
            filename = Path(raw_ref).name

            photo = None
            if filename in photo_lookup:
                photo = photo_lookup[filename]
            else:
                for p in media['photos']:
                    if filename.lower() in p['name'].lower() or p['name'].startswith(filename[:10]):
                        photo = p
                        break

            if photo:
                if photo['date'] != last_date:
                    photo_count_today = 0
                    last_date = photo['date']

                if photo_count_today < MAX_PHOTOS_PER_DAY:
                    photo_count_today += 1
                    is_full = 'full-width' if photo_count_today == 1 else ''
                    photo_html = f'<figure class="photo {is_full}" data-fancybox="gallery" data-src="{photo["rel_path"]}" data-caption="{caption}">'
                    photo_html += f'<a href="{photo["rel_path"]}" class="lightbox-link">'
                    photo_html += f'<img src="{photo["rel_path"]}" alt="{photo["name"]}" loading="lazy">'
                    photo_html += '</a>'
                    if caption:
                        photo_html += f'<figcaption>{caption.strip("*").strip()}</figcaption>'
                    photo_html += '</figure>'
                    processed_lines.append(photo_html)
            continue

        processed_lines.append(line)

    return '\n'.join(processed_lines)


def convert_obsidian_callouts(content):
    """Convert Obsidian callouts > [!type] to styled HTML."""
    lines = content.split('\n')
    processed_lines = []
    in_callout = False
    callout_type = ''
    callout_content = []

    for line in lines:
        callout_match = re.match(r'^>\s*\[!(\w+)\]\s*(.*)$', line)
        if callout_match:
            if in_callout:
                # Close previous callout
                processed_lines.append(f'<div class="callout callout-{callout_type}">')
                processed_lines.append(f'<div class="callout-content">{" ".join(callout_content)}</div>')
                processed_lines.append('</div>')
                callout_content = []
            in_callout = True
            callout_type = callout_match.group(1).lower()
            callout_title = callout_match.group(2).strip()
            processed_lines.append(f'<div class="callout callout-{callout_type}">')
            if callout_title:
                processed_lines.append(f'<div class="callout-title">{callout_title}</div>')
            processed_lines.append('<div class="callout-content">')
        elif in_callout and line.startswith('>'):
            # Inside callout
            content_text = line.lstrip('>').strip()
            if content_text:
                callout_content.append(content_text)
        elif in_callout and not line.startswith('>'):
            # End of callout
            processed_lines.append('</div></div>')
            in_callout = False
            callout_content = []
            processed_lines.append(line)
        else:
            processed_lines.append(line)

    # Close any open callout
    if in_callout:
        processed_lines.append('</div></div>')

    return '\n'.join(processed_lines)


def convert_wikilinks(content):
    """Convert [[Page Name]] to plain text or styled links."""
    # Convert [[Phoenix]] to just "Phoenix" (or could be styled links)
    return re.sub(r'\[\[([^\]]+)\]\]', r'\1', content)


def parse_obsidian_markdown(content, media):
    """Parse Obsidian markdown and convert to HTML, preserving all formatting."""
    # Extract front matter
    metadata = extract_metadata(content)

    # Remove front matter from content
    content = re.sub(r'^---\n.*?\n---\n', '', content, count=1, flags=re.DOTALL)

    # Convert Obsidian-specific syntax
    content = replace_obsidian_images(content, media)
    content = convert_obsidian_callouts(content)
    content = convert_wikilinks(content)

    # Use Python markdown library to convert to HTML
    md = markdown.Markdown(extensions=[
        'extra',      # Tables, fenced code, etc.
        'nl2br',      # Newlines to <br>
        'sane_lists', # Better list handling
    ])

    html_content = md.convert(content)
    return html_content, metadata


def generate_html(journal_files, media, template_path):
    """Generate HTML from all journal files."""
    with open(template_path, 'r') as f:
        template_str = f.read()

    template = Template(template_str)

    # Process each journal file
    all_html = []
    all_embedded_photos = set()
    all_embedded_videos = set()

    for jf in journal_files:
        with open(jf, 'r') as f:
            content = f.read()

        html_content, metadata = parse_obsidian_markdown(content, media)

        # Extract title from metadata or filename
        title = metadata.get('title', jf.stem)

        # Wrap each journal in a section
        journal_html = f'<div class="journal-entry">'
        journal_html += f'<h1 class="journal-title">{title}</h1>'

        # Add metadata header
        if metadata:
            journal_html += '<div class="journal-meta">'
            if 'created' in metadata:
                journal_html += f'<span class="meta-item">📅 Created: {metadata["created"]}</span>'
            if 'updated' in metadata:
                journal_html += f'<span class="meta-item">🔄 Updated: {metadata["updated"]}</span>'
            if 'tags' in metadata:
                journal_html += f'<span class="meta-item">🏷️ {metadata["tags"]}</span>'
            journal_html += '</div>'

        journal_html += html_content
        journal_html += '</div>'

        all_html.append(journal_html)

    body_content = '\n\n<hr class="journal-divider">\n\n'.join(all_html)

    return template.render(
        title="China Trip 2026",
        content=body_content
    )


def main():
    print("=" * 60)
    print("China 2026 Travel Journal Builder (Enhanced v2)")
    print("=" * 60)

    # Scan media files
    print(f"\nScanning {PHOTOS_FOLDER}...")
    media = scan_media_files()
    print(f"  Found {len(media['photos'])} photos")
    print(f"  Found {len(media['videos'])} videos")

    # Read journal entries
    def _journal_sort_key(f):
        """Extract journal number for natural sorting."""
        m = re.search(r'Journal\s+(\d+)', f.name)
        return int(m.group(1)) if m else 999

    journal_files = sorted(
        [f for f in JOURNAL_DIR.glob("Journal *.md") if f.name not in SKIP_FILES],
        key=_journal_sort_key
    )

    if not journal_files:
        print(f"\n✗ No journal files found in {JOURNAL_DIR}")
        return

    print(f"\nReading {len(journal_files)} journal files from {JOURNAL_DIR}...")
    for jf in journal_files:
        print(f"  - {jf.name}")

    # Create output directory
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    # Copy media files
    print(f"\nCopying media files to {MEDIA_OUTPUT_DIR}...")
    if MEDIA_OUTPUT_DIR.exists():
        shutil.rmtree(MEDIA_OUTPUT_DIR)
    MEDIA_OUTPUT_DIR.mkdir(parents=True)

    media_copied = 0
    for p in media['photos']:
        shutil.copy2(p['path'], MEDIA_OUTPUT_DIR / p['name'])
        media_copied += 1
    for v in media['videos']:
        shutil.copy2(v['path'], MEDIA_OUTPUT_DIR / v['name'])
        media_copied += 1
    print(f"  Copied {media_copied} media files")

    # Generate HTML
    print("\nGenerating HTML with proper markdown formatting...")
    html_content = generate_html(journal_files, media, TEMPLATE_FILE)

    html_path = OUTPUT_FOLDER / "china-journal.html"
    with open(html_path, 'w') as f:
        f.write(html_content)

    html_size = html_path.stat().st_size
    print(f"HTML generated: {html_path}")
    print(f"File size: {html_size:,} bytes ({html_size/1024:.1f} KB)")

    # Generate PDF
    pdf_path = OUTPUT_FOLDER / "china-journal.pdf"
    print("\nGenerating PDF...")
    try:
        html_doc = HTML(string=html_content)
        html_doc.write_pdf(pdf_path)
        pdf_size = pdf_path.stat().st_size
        print(f"PDF generated: {pdf_path}")
        print(f"PDF file size: {pdf_size:,} bytes ({pdf_size/1024:.1f} KB)")
    except Exception as e:
        print(f"PDF generation failed: {e}")

    # Copy to hermes-outputs
    today = datetime.now().strftime("%Y-%m-%d")
    dest_dir = Path("/opt/projects/hermes-outputs/research")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_html = dest_dir / f"china-journal-{today}.html"
    shutil.copy2(html_path, dest_html)
    print(f"\n✓ Copied to: {dest_html}")

    print("\n" + "=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(f"  HTML: {html_path}")
    print(f"  PDF:  {pdf_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
