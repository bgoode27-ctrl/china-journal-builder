#!/usr/bin/env python3
"""
China Travel Journal Builder v3
- Reads explicit image references from Obsidian journal markdown
- Auto-rotates images using EXIF Orientation
- Converts HEIC to web JPG and compresses for Vercel
- Matches images to journal dates and warns on mismatches
- Builds Chinese-themed, password-protected HTML + PDF
- Writes deploy-ready files to repo root (index.html, assets/)
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from PIL import Image, ExifTags
from pillow_heif import register_heif_opener
import markdown
from jinja2 import Template
from weasyprint import HTML

register_heif_opener()

# Configuration
HOME = Path.home()
VAULT = HOME / "Documents/global/Research/China"
PHOTOS_FOLDER = VAULT / "raw/assets/photos/China2026"
JOURNAL_DIR = VAULT / "wiki/journal"
REPO_ROOT = HOME / "Documents/Projects"
TEMPLATE_FILE = REPO_ROOT / "journal-template-v3.html"
OUTPUT_FOLDER = REPO_ROOT / "build-v3"
DEPLOY_ASSETS_DIR = REPO_ROOT / "assets"

SKIP_FILES = {"Journal Entry Template 3.md"}
PASSWORD = "fubaoshu"
MAX_PHOTO_WIDTH = 1600
JPEG_QUALITY = 80


def days_within(d1, d2, tolerance=1):
    """Return True if two YYYY-MM-DD strings are within tolerance days."""
    try:
        a = datetime.strptime(d1, "%Y-%m-%d")
        b = datetime.strptime(d2, "%Y-%m-%d")
        return abs((a - b).days) <= tolerance
    except Exception:
        return False


def parse_date_from_journal(content):
    """Extract the journal date(s) from front matter or heading."""
    dates = []
    # From **Date**: 2026-05-12 / 2026-05-13 (Mon–Tue)
    m = re.search(r'\*\*Date\*\*:\s*(\d{4}-\d{2}-\d{2})(?:\s*/\s*(\d{4}-\d{2}-\d{2}))?', content)
    if m:
        dates.append(m.group(1))
        if m.group(2):
            dates.append(m.group(2))
    # From heading: ## 🗓️ Day 1 — Phoenix to Hong Kong
    return dates


def parse_image_date_from_filename(filename):
    """Extract YYYY-MM-DD from filenames like IMG_20260513_173732_545.jpg"""
    m = re.search(r'(\d{4})(\d{2})(\d{2})_', filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # Old iPhone filenames like IMG_0918.jpg don't have dates
    return None


def get_exif_datetime(image_path):
    """Read DateTimeOriginal from EXIF if present."""
    try:
        img = Image.open(image_path)
        exif = img._getexif()
        if exif:
            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)
                if tag == "DateTimeOriginal":
                    # value like "2026:05:13 17:37:32"
                    return value[:10].replace(":", "-")
    except Exception:
        pass
    return None


def get_image_date(image_path):
    """Best-effort date for an image file."""
    dt = get_exif_datetime(image_path)
    if dt:
        return dt
    return parse_image_date_from_filename(image_path.name)


def apply_exif_orientation(img):
    """Rotate image according to EXIF Orientation so it appears upright."""
    try:
        exif = img._getexif()
        if exif is None:
            return img
        orientation = None
        for tag_id, value in exif.items():
            tag = ExifTags.TAGS.get(tag_id, tag_id)
            if tag == "Orientation":
                orientation = value
                break
        if orientation == 3:
            img = img.rotate(180, expand=True)
        elif orientation == 6:
            img = img.rotate(270, expand=True)
        elif orientation == 8:
            img = img.rotate(90, expand=True)
        elif orientation in (2, 4, 5, 7):
            # mirrored orientations are rare on phones; just rotate, don't mirror
            if orientation == 2:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 4:
                img = img.rotate(180, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 5:
                img = img.rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 7:
                img = img.rotate(270, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
    except Exception:
        pass
    return img


def process_image(src_path, deploy_assets_dir, journal_dates):
    """Convert/compress/rotate an image and return deploy filename + caption warning."""
    src_path = Path(src_path)
    deploy_name = src_path.stem + ".jpg"
    deploy_path = deploy_assets_dir / deploy_name

    img = Image.open(src_path)
    img = apply_exif_orientation(img)

    # Convert palette/alpha to RGB
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize if too large
    if img.width > MAX_PHOTO_WIDTH:
        ratio = MAX_PHOTO_WIDTH / img.width
        new_size = (MAX_PHOTO_WIDTH, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Save compressed JPG
    deploy_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(deploy_path, "JPEG", quality=JPEG_QUALITY, optimize=True)

    # Date warning (allow images from the previous day for late-night travel entries)
    warning = None
    img_date = get_image_date(src_path)
    if img_date and journal_dates:
        if not any(days_within(img_date, jd, tolerance=1) for jd in journal_dates):
            warning = f"Image date {img_date} does not match journal date(s) {', '.join(journal_dates)}"

    return deploy_name, warning


def extract_metadata(content):
    """Extract YAML front matter metadata."""
    metadata = {}
    match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
    if match:
        for line in match.group(1).split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                metadata[key.strip()] = value.strip()
    return metadata


def convert_obsidian_callouts(content):
    """Convert Obsidian callouts > [!type] to styled HTML."""
    lines = content.split('\n')
    out = []
    in_callout = False
    callout_type = ''
    callout_title = ''
    callout_content = []

    def flush():
        nonlocal in_callout, callout_type, callout_title, callout_content
        if not in_callout:
            return
        out.append(f'<div class="callout callout-{callout_type}">')
        if callout_title:
            out.append(f'<div class="callout-title">{callout_title}</div>')
        out.append('<div class="callout-content">')
        out.append(markdown.markdown('\n'.join(callout_content)))
        out.append('</div></div>')
        in_callout = False
        callout_type = ''
        callout_title = ''
        callout_content = []

    for line in lines:
        callout_match = re.match(r'^>\s*\[!(\w+)\]\s*(.*)$', line)
        if callout_match:
            flush()
            in_callout = True
            callout_type = callout_match.group(1).lower()
            callout_title = callout_match.group(2).strip()
            continue
        if in_callout:
            if line.startswith('>'):
                text = line.lstrip('>').strip()
                if text:
                    callout_content.append(text)
            else:
                flush()
                out.append(line)
        else:
            out.append(line)
    flush()
    return '\n'.join(out)


def convert_wikilinks(content):
    """Convert [[Page Name]] to plain text."""
    return re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', content)


def replace_image_references(content, journal_dates, warnings):
    """Replace Obsidian ![[path]] with processed <figure> HTML."""
    photo_count_today = defaultdict(int)
    last_date = None

    pattern = re.compile(r'^!\[\[([^\]]+)\]\]\s*\n?(?:\s*\*([^\*\n]+)\*\s*)?$', re.MULTILINE)

    def repl(m):
        nonlocal last_date
        raw_ref = m.group(1).strip()
        caption = m.group(2).strip() if m.group(2) else ""
        filename = Path(raw_ref).name
        src_path = PHOTOS_FOLDER / filename
        if not src_path.exists():
            src_path = VAULT / raw_ref
        if not src_path.exists():
            warnings.append(f"Missing file: {raw_ref}")
            return f'<p><em>Missing media: {filename}</em></p>'

        ext = src_path.suffix.lower()
        video_exts = {'.mp4', '.mov', '.MOV', '.MP4'}
        if ext in video_exts:
            deploy_name = filename
            deploy_path = DEPLOY_ASSETS_DIR / deploy_name
            deploy_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, deploy_path)
            rel_path = f"assets/{deploy_name}"
            cap_html = f'<p class="video-note">{caption}</p>' if caption else ""
            return f'''<div class="video-container">
    <video controls preload="metadata">
        <source src="{rel_path}" type="video/mp4">
        Your browser does not support video.
    </video>
    {cap_html}
</div>'''

        deploy_name, warning = process_image(src_path, DEPLOY_ASSETS_DIR, journal_dates)
        if warning:
            warnings.append(f"{filename}: {warning}")

        rel_path = f"assets/{deploy_name}"

        day_key = journal_dates[0] if journal_dates else "unknown"
        if day_key != last_date:
            photo_count_today[day_key] = 0
            last_date = day_key
        photo_count_today[day_key] += 1
        is_full = ' full-width' if photo_count_today[day_key] == 1 else ''

        cap_html = f'<figcaption>{caption}</figcaption>' if caption else ""
        return f'''<figure class="photo{is_full}">
    <img src="{rel_path}" alt="{filename}" loading="lazy">
    {cap_html}
</figure>'''

    content = pattern.sub(repl, content)
    return content


def parse_journal_file(path):
    """Parse a single journal markdown file into HTML + metadata + warnings."""
    content = path.read_text(encoding='utf-8')
    metadata = extract_metadata(content)

    # Remove front matter from content
    content = re.sub(r'^---\n.*?\n---\n', '', content, count=1, flags=re.DOTALL)

    journal_dates = parse_date_from_journal(content)
    warnings = []

    # Convert Obsidian syntax
    content = replace_image_references(content, journal_dates, warnings)
    content = convert_obsidian_callouts(content)
    content = convert_wikilinks(content)

    # Convert markdown to HTML
    md = markdown.Markdown(extensions=['extra', 'nl2br', 'sane_lists'])
    html_content = md.convert(content)

    title = metadata.get('title', path.stem)
    return {
        'title': title,
        'metadata': metadata,
        'html': html_content,
        'warnings': warnings,
        'dates': journal_dates,
        'path': path,
    }


def journal_sort_key(path):
    m = re.search(r'Journal\s+(\d+)', path.name)
    return int(m.group(1)) if m else 999


def generate_html(journal_files, template_path, password):
    with open(template_path, 'r', encoding='utf-8') as f:
        template = Template(f.read())

    entries_html = []
    for jf in journal_files:
        entry = parse_journal_file(jf)
        meta_html = '<div class="journal-meta">'
        if entry['metadata'].get('created'):
            meta_html += f'<span class="meta-item">📅 Created: {entry["metadata"]["created"]}</span>'
        if entry['metadata'].get('updated'):
            meta_html += f'<span class="meta-item">🔄 Updated: {entry["metadata"]["updated"]}</span>'
        if entry['dates']:
            meta_html += f'<span class="meta-item">📍 Date: {", ".join(entry["dates"])}</span>'
        if entry['metadata'].get('tags'):
            meta_html += f'<span class="meta-item">🏷️ {entry["metadata"]["tags"]}</span>'
        meta_html += '</div>'

        warnings_html = ""
        if entry['warnings']:
            warnings_html = '<div style="background:#fbeae9;border-left:4px solid #B92B27;padding:12px 16px;margin:16px 0;border-radius:4px;">'
            warnings_html += '<strong>⚠️ Image warnings:</strong><ul>'
            for w in entry['warnings']:
                warnings_html += f'<li>{w}</li>'
            warnings_html += '</ul></div>'

        entry_html = f'''<article class="journal-entry">
<h1 class="journal-title">{entry["title"]}</h1>
{meta_html}
{warnings_html}
{entry["html"]}
</article>'''
        entries_html.append(entry_html)

    body = '\n<hr class="journal-divider">\n'.join(entries_html)

    # Inject password into the template
    rendered = template.render(title="China Trip 2026", content=body)
    rendered = rendered.replace("const CORRECT_PASSWORD='***';", "const CORRECT_PASSWORD='" + PASSWORD + "';")
    return rendered


def main():
    print("=" * 60)
    print("China 2026 Travel Journal Builder v3")
    print("=" * 60)

    journal_files = sorted(
        [f for f in JOURNAL_DIR.glob("Journal *.md") if f.name not in SKIP_FILES],
        key=journal_sort_key,
    )
    if not journal_files:
        print(f"✗ No journal files found in {JOURNAL_DIR}")
        return

    print(f"\nFound {len(journal_files)} journal files")
    for jf in journal_files:
        print(f"  - {jf.name}")

    # Clean deploy assets
    print(f"\nPreparing deploy assets folder: {DEPLOY_ASSETS_DIR}")
    if DEPLOY_ASSETS_DIR.exists():
        shutil.rmtree(DEPLOY_ASSETS_DIR)
    DEPLOY_ASSETS_DIR.mkdir(parents=True)

    # Generate HTML
    print("\nGenerating Chinese-themed HTML...")
    html_content = generate_html(journal_files, TEMPLATE_FILE, PASSWORD)

    html_path = REPO_ROOT / "index.html"
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    html_size = html_path.stat().st_size
    print(f"HTML generated: {html_path} ({html_size:,} bytes)")

    # Generate PDF (exclude video sources to keep file small)
    pdf_path = REPO_ROOT / "china-journal.pdf"
    print("\nGenerating PDF...")
    try:
        pdf_html = re.sub(
            r'<div class="video-container">.*?</div>',
            '<div class="video-container"><p><em>Video not included in PDF version.</em></p></div>',
            html_content,
            flags=re.DOTALL,
        )
        HTML(string=pdf_html, base_url=str(REPO_ROOT)).write_pdf(pdf_path)
        pdf_size = pdf_path.stat().st_size
        print(f"PDF generated: {pdf_path} ({pdf_size:,} bytes)")
    except Exception as e:
        print(f"PDF generation failed: {e}")

    # Copy to build-v3 and hermes-outputs
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    shutil.copy2(html_path, OUTPUT_FOLDER / "china-journal.html")
    if pdf_path.exists():
        shutil.copy2(pdf_path, OUTPUT_FOLDER / "china-journal.pdf")

    today = datetime.now().strftime("%Y-%m-%d")
    dest_dir = REPO_ROOT / "hermes-outputs/research"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(html_path, dest_dir / f"china-journal-{today}.html")

    # Summary
    asset_size = sum(f.stat().st_size for f in DEPLOY_ASSETS_DIR.rglob("*") if f.is_file())
    print(f"\nDeploy assets: {DEPLOY_ASSETS_DIR} ({asset_size / 1024 / 1024:.1f} MB, {len(list(DEPLOY_ASSETS_DIR.rglob('*')))} files)")
    print("\n" + "=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(f"  HTML:  {html_path}")
    print(f"  PDF:   {pdf_path}")
    print(f"  Assets: {DEPLOY_ASSETS_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
