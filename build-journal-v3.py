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


def process_image(src_path, deploy_assets_dir, journal_dates, max_width=None, thumb_dir=None):
    """Convert/compress/rotate an image and return deploy filename + caption warning.

    If thumb_dir is set, also generate a thumbnail of max_width for gallery grids.
    """
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

    # Save full compressed JPG (default MAX_PHOTO_WIDTH)
    full_width = max_width or MAX_PHOTO_WIDTH
    if img.width > full_width:
        ratio = full_width / img.width
        full_img = img.resize((full_width, int(img.height * ratio)), Image.LANCZOS)
    else:
        full_img = img.copy()

    deploy_path.parent.mkdir(parents=True, exist_ok=True)
    full_img.save(deploy_path, "JPEG", quality=JPEG_QUALITY, optimize=True)

    thumb_name = None
    if thumb_dir is not None:
        thumb_dir = Path(thumb_dir)
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb_name = deploy_name
        thumb_path = thumb_dir / thumb_name
        thumb_width = 400
        if img.width > thumb_width:
            ratio = thumb_width / img.width
            thumb_img = img.resize((thumb_width, int(img.height * ratio)), Image.LANCZOS)
        else:
            thumb_img = img.copy()
        thumb_img.save(thumb_path, "JPEG", quality=75, optimize=True)

    # Date warning (allow images from the previous day for late-night travel entries)
    warning = None
    img_date = get_image_date(src_path)
    if img_date and journal_dates:
        if not any(days_within(img_date, jd, tolerance=1) for jd in journal_dates):
            warning = f"Image date {img_date} does not match journal date(s) {', '.join(journal_dates)}"

    return deploy_name, thumb_name, warning


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
        # Strip literal outer [...] wrappers that wrap the whole content
        # (a common typo when authoring Obsidian callouts — they look like
        # empty link placeholders in the rendered output)
        body = '\n'.join(callout_content).strip()
        if body.startswith('[') and body.endswith(']') and body.count('[') == 1 and body.count(']') == 1:
            body = body[1:-1].strip()
        out.append(f'<div class="callout callout-{callout_type}">')
        if callout_title:
            out.append(f'<div class="callout-title">{callout_title}</div>')
        out.append('<div class="callout-content">')
        out.append(markdown.markdown(body))
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


GALLERY_FENCE = re.compile(r'^::gallery\s*\n(.*?)\n::\s*$', re.MULTILINE | re.DOTALL)
IMAGE_LINE = re.compile(r'^!\[\[([^\]]+)\]\]\s*$', re.MULTILINE)
CAPTION_LINE = re.compile(r'^\*([^\*\n]+)\*\s*$', re.MULTILINE)


def _resolve_image_path(raw_ref):
    """Return the filesystem Path for an Obsidian image reference."""
    filename = Path(raw_ref).name
    src_path = PHOTOS_FOLDER / filename
    if not src_path.exists():
        src_path = VAULT / raw_ref
    return src_path if src_path.exists() else None


def _process_inline_image(raw_ref, caption, journal_dates, warnings, thumb_dir=None):
    """Process a single ![[image]] into a <figure> or gallery item HTML."""
    filename = Path(raw_ref).name
    src_path = _resolve_image_path(raw_ref)
    if src_path is None:
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

    deploy_name, thumb_name, warning = process_image(
        src_path, DEPLOY_ASSETS_DIR, journal_dates, thumb_dir=thumb_dir
    )
    if warning:
        warnings.append(f"{filename}: {warning}")

    full_rel = f"assets/{deploy_name}"
    cap_html = f'<figcaption>{caption}</figcaption>' if caption else ""

    if thumb_dir is not None:
        thumb_rel = f"assets/thumbs/{thumb_name}"
        return f'''<figure class="gallery-item">
    <a href="{full_rel}" data-lightbox="gallery" data-caption="{caption}">
        <img src="{thumb_rel}" alt="{filename}" loading="lazy">
    </a>
    {cap_html}
</figure>'''

    return f'''<figure class="photo">
    <img src="{full_rel}" alt="{filename}" loading="lazy">
    {cap_html}
</figure>'''


def _render_gallery_block(block_body, journal_dates, warnings):
    """Render a ::gallery ... :: block into a thumbnail grid with lightbox."""
    thumb_dir = DEPLOY_ASSETS_DIR / "thumbs"
    items = []

    # Normalize lines and pair image references with optional caption lines
    lines = [line for line in block_body.splitlines() if line.strip()]
    i = 0
    while i < len(lines):
        img_match = IMAGE_LINE.match(lines[i])
        if not img_match:
            i += 1
            continue
        raw_ref = img_match.group(1).strip()
        caption = ""
        if i + 1 < len(lines):
            cap_match = CAPTION_LINE.match(lines[i + 1])
            if cap_match:
                caption = cap_match.group(1).strip()
                i += 1
        items.append(_process_inline_image(raw_ref, caption, journal_dates, warnings, thumb_dir=thumb_dir))
        i += 1

    if not items:
        return ''
    return '\n'.join(['<div class="gallery-grid">'] + items + ['</div>'])


def replace_image_references(content, journal_dates, warnings):
    """Replace Obsidian ![[path]] with processed <figure> HTML and gallery blocks."""
    photo_count_today = 0
    last_date = None
    day_key = journal_dates[0] if journal_dates else "unknown"

    def gallery_repl(m):
        return _render_gallery_block(m.group(1), journal_dates, warnings)

    content = GALLERY_FENCE.sub(gallery_repl, content)

    pattern = re.compile(r'^!\[\[([^\]]+)\]\]\s*\n?(?:\s*\*([^\*\n]+)\*\s*)?$', re.MULTILINE)

    def repl(m):
        nonlocal photo_count_today, last_date
        raw_ref = m.group(1).strip()
        caption = m.group(2).strip() if m.group(2) else ""

        if day_key != last_date:
            photo_count_today = 0
            last_date = day_key
        photo_count_today += 1
        is_full = ' full-width' if photo_count_today == 1 else ''

        figure_html = _process_inline_image(raw_ref, caption, journal_dates, warnings, thumb_dir=None)
        # Inject full-width class into the first photo of each entry
        if 'class="photo"' in figure_html and is_full:
            figure_html = figure_html.replace('class="photo"', f'class="photo{is_full}"')
        return figure_html

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
