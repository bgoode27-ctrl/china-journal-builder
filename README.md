# China Journal Builder

A self-contained pipeline that turns Obsidian journal notes + phone photos into a password-protected, Chinese-themed travel journal website deployed on Vercel.

---

## What it does

1. Reads journal Markdown files from the Obsidian vault (`~/Documents/global/Research/China/wiki/journal/`)
2. Reads photos from the Obsidian vault photos folder (`~/Documents/global/Research/China/raw/assets/photos/China2026/`)
3. Matches each photo to the journal entry date, auto-rotates via EXIF, converts HEIC → JPG, and compresses for the web
4. Builds a Chinese-themed `index.html` with password protection
5. Generates a PDF version
6. Copies deploy-ready files to the repo root so Vercel can serve them

---

## File layout

| Path | What it is |
|---|---|
| `build-journal-v3.py` | Main build script |
| `journal-template-v3.html` | Chinese-themed HTML/CSS template |
| `index.html` | Live website (deployed to Vercel) |
| `china-journal.pdf` | Generated PDF version |
| `assets/` | Compressed photos + video used by `index.html` |
| `.gitignore` | Keeps the 6 GB raw media out of Git |
| `china-journal-raw-media/` | Raw media moved out of the Git workspace |
| `vercel.json` | Minimal Vercel config |

---

## How to build and publish

### 1. Add or edit journal entries

In Obsidian, edit files in:

```
~/Documents/global/Research/China/wiki/journal/
```

Use the normal Markdown format. Photos are referenced like this:

```markdown
![[raw/assets/photos/China2026/IMG_20260514_105849_424.jpg]]
*Caption text goes here*
```

The builder uses the exact photo references in each journal, so the images always match the day they’re under.

### 2. Run the builder

```bash
cd ~/Documents/Projects
python3 build-journal-v3.py
```

This writes:
- `index.html`
- `china-journal.pdf`
- `assets/` (compressed images and video)

### 3. Review locally

Open `index.html` in a browser. The password is the same as configured in the script.

### 4. Commit and push

```bash
cd ~/Documents/Projects
git add index.html china-journal.pdf assets/ build-journal-v3.py journal-template-v3.html .gitignore README.md
git commit -m "Rebuild China journal: <describe changes>"
git push origin main
```

Vercel auto-deploys on every push.

---

## Important notes

- **Raw media stays out of Git.** The 6 GB `China Trip/build/` folder has been moved to `china-journal-raw-media/` and is ignored. Only the compressed `assets/` folder is deployed.
- **Password is set in the script.** Edit `PASSWORD` near the top of `build-journal-v3.py` to change it.
- **Image orientation is fixed automatically.** The builder reads EXIF orientation tags and rotates before resizing.
- **HEIC files are converted to JPG.** No HEIC files are deployed.
- **Date matching allows a 1-day tolerance.** Late-night travel photos (e.g., May 13 photos under the May 14 journal) are accepted.

---

## Live site

URL: `https://china-journal-builder.vercel.app`

Password: `fubaoshu`

---

## Troubleshooting

### `ModuleNotFoundError` for Pillow / markdown / etc.

Install the required Python packages:

```bash
python3 -m pip install --user --break-system-packages jinja2 markdown pillow-heif piexif weasyprint
```

### Images are not upright

The builder auto-rotates using EXIF. If a photo is still sideways after publishing, run the builder again and check the build output for any EXIF warnings.

### Vercel deploy looks old

Make sure you committed `index.html` and `assets/` to the repo root (not inside the `China Trip/` folder), then push.
