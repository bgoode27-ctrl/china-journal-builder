#!/usr/bin/env python3
"""
China Travel Journal Builder (Enhanced)
Generates HTML with photo grid, captions, gallery, and lightbox.
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime
import markdown
from jinja2 import Template

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
            # Try multiple patterns
            match = re.search(r'(?:IMG_|VID_|img_)(\d{4})(\d{2})(\d{2})_(\d{6})', f.name)
            if not match:
                match = re.search(r'IMG_(\d{4})', f.name)
                if match:
                    year = int(match.group(1))
                    month, day = 5, 13  # fallback
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


def parse_obsidian_markdown(content, media):
    """Parse Obsidian markdown and convert ![[file]] syntax to HTML."""
    photo_lookup = {p['name']: p for p in media['photos']}
    video_lookup = {v['name']: v for v in media['videos']}

    lines = content.split('\n')
    html_lines = []
    current_date = None
    photo_count_today = 0
    last_date = None
    in_list = False
    embedded_photos = set()
    embedded_videos = set()

    for line in lines:
        # Check for date headers
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

        # Handle videos first (before photos, since photo regex also matches .mp4)
        video_match = re.match(r'^!\[\[([^\]]+\.(mp4|mov|MP4|MOV))\]\]\s*(.*)$', line)
        if video_match:
            raw_ref = video_match.group(1).strip()
            caption = video_match.group(3).strip()

            # Extract just the filename
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
                embedded_videos.add(video['name'])
                html_lines.append('<div class="video-container">')
                html_lines.append(f'<video controls preload="metadata"><source src="{video["rel_path"]}" type="video/mp4">Your browser does not support video.</video>')
                if caption:
                    html_lines.append(f'<p class="video-note">{caption.strip("*").strip()}</p>')
                html_lines.append('</div>')
            continue

        # Handle ![[filename]] syntax for photos (non-video files)
        photo_match = re.match(r'^!\[\[([^\]]+)\]\]\s*(.*)$', line)
        if photo_match:
            raw_ref = photo_match.group(1).strip()
            caption = photo_match.group(2).strip()

            # Extract just the filename
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
                embedded_photos.add(photo['name'])
                if photo['date'] != last_date:
                    photo_count_today = 0
                    last_date = photo['date']

                if photo_count_today < MAX_PHOTOS_PER_DAY:
                    photo_count_today += 1
                    is_full = 'full-width' if photo_count_today == 1 else ''
                    html_lines.append(f'<figure class="photo {is_full}" data-fancybox="gallery" data-src="{photo["rel_path"]}" data-caption="{caption}">')
                    html_lines.append(f'<a href="{photo["rel_path"]}" class="lightbox-link">')
                    html_lines.append(f'<img src="{photo["rel_path"]}" alt="{photo["name"]}" loading="lazy">')
                    html_lines.append('</a>')
                    if caption:
                        html_lines.append(f'<figcaption>{caption.strip("*").strip()}</figcaption>')
                    html_lines.append('</figure>')
            continue

        # Regular markdown
        if line.strip() and not line.startswith('#'):
            if line.strip().startswith('* '):
                if not in_list:
                    html_lines.append('<ul>')
                    in_list = True
                bullet_content = line.strip()[2:]
                html_lines.append(f'<li>{bullet_content}</li>')
            else:
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                html_lines.append(f'<p>{line.strip()}</p>')
        elif line.startswith('# ') and not html_lines:
            title = line[2:].strip()
            html_lines.insert(0, f'<h1>{title}</h1>')

    if in_list:
        html_lines.append('</ul>')

    return '\n'.join(html_lines), embedded_photos, embedded_videos


def generate_html(content, media, template_path):
    """Generate HTML from markdown content."""
    with open(template_path, 'r') as f:
        template_str = f.read()

    template = Template(template_str)

    body_content, embedded_photos, embedded_videos = parse_obsidian_markdown(content, media)

    return template.render(
        title="China Trip 2026",
        content=body_content
    ), embedded_photos, embedded_videos


def main():
    print("=" * 60)
    print("China 2026 Travel Journal Builder (Enhanced)")
    print("=" * 60)

    # Check dependencies
    try:
        from weasyprint import HTML
        print("✓ WeasyPrint available")
    except ImportError:
        print("✗ WeasyPrint not installed - proceeding with HTML only")
        HTML = None

    # Scan media files
    print(f"\nScanning {PHOTOS_FOLDER}...")
    media = scan_media_files()
    print(f"  Found {len(media['photos'])} photos")
    print(f"  Found {len(media['videos'])} videos")

    # Read journal entries from all 10 files (natural sort by journal number)
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
    content_parts = []
    for jf in journal_files:
        print(f"  - {jf.name}")
        with open(jf, 'r') as f:
            content_parts.append(f.read())
    content = "\n\n---\n\n".join(content_parts)
    
    if not content.strip():
        print("  All files are empty")
        return

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
    print("\nGenerating HTML...")
    html_content, embedded_photos, embedded_videos = generate_html(content, media, TEMPLATE_FILE)

    html_path = OUTPUT_FOLDER / "china-journal.html"
    with open(html_path, 'w') as f:
        f.write(html_content)
    
    html_size = html_path.stat().st_size
    print(f"HTML generated: {html_path}")
    print(f"File size: {html_size:,} bytes ({html_size/1024:.1f} KB)")

    # Also generate PDF
    pdf_path = OUTPUT_FOLDER / "china-journal.pdf"
    if HTML is not None:
        print("\nGenerating PDF (this may take a moment)...")
        try:
            html_doc = HTML(string=html_content)
            html_doc.write_pdf(pdf_path)
            pdf_size = pdf_path.stat().st_size
            print(f"PDF generated: {pdf_path}")
            print(f"PDF file size: {pdf_size:,} bytes ({pdf_size/1024:.1f} KB, {pdf_size/(1024*1024):.1f} MB)")
        except Exception as e:
            print(f"PDF generation failed: {e}")

    # Copy to hermes-outputs
    today = datetime.now().strftime("%Y-%m-%d")
    dest_dir = Path("/opt/projects/hermes-outputs/research")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_html = dest_dir / f"china-journal-{today}.html"
    shutil.copy2(html_path, dest_html)
    print(f"\n✓ Copied to: {dest_html}")

    # Summary
    print("\n" + "=" * 60)
    print("BUILD SUMMARY")
    print("=" * 60)
    print(f"  Photos scanned:    {len(media['photos'])}")
    print(f"  Videos scanned:    {len(media['videos'])}")
    print(f"  Photos embedded:   {len(embedded_photos)}")
    print(f"  Videos embedded:   {len(embedded_videos)}")
    print(f"  Media copied:      {media_copied}")
    print(f"  HTML size:         {html_size:,} bytes")
    if HTML is not None:
        print(f"  PDF size:          {pdf_size:,} bytes ({pdf_size/(1024*1024):.1f} MB)")
    print(f"  Output:            {html_path}")
    print(f"  Copy:              {dest_html}")
    print("=" * 60)


if __name__ == "__main__":
    main()
