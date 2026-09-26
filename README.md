# Abiotic Factor – Field Checklist

A free, **unofficial** fan-made checklist for *Abiotic Factor*. Tick off achievements and collectibles and see at a glance what is done and what is still missing, per category and overall. It runs entirely in your browser: no account, no installation, and your progress stays on your device.

**▶ Online demo:** https://vibecodescientist.github.io/abiotic-factor-checklist/
**⬇ Download:** [ZIP of the latest version](https://github.com/VibeCodeScientist/abiotic-factor-checklist/archive/refs/heads/main.zip). Unzip it and double-click `index.html`; it also works offline.

| Category | Entries |
|---|---|
| Achievements | 53 (PC; the PS5-only "Pure Science" is left out) |
| Collectibles | 38 |
| Photo Frames | 23 |
| Wall Decorations | 51 (wall art + decorations) |
| Television | 11 |
| Armor Sets | 31 |
| Lab Masks | 9 (all colour variants) |
| Trinkets | 25 |
| Full Body Suits | 9 |
| Backpacks | 19 |
| Wristwatches | 7 |
| Antelights | 8 (all colours) |
| **Total** | **284** |

## How to use

- **Categories:** They are listed in the sidebar with progress bars. The top of the sidebar shows your overall progress.
- **Ticking off:** Click a tile, a picture, a name or the checkbox.
- **Wiki link:** **↗ / Wiki** opens the entry's wiki page, e.g. for locations.
- **Search:** Press `/` to jump to the search field and `Esc` to clear it. Turn on **All categories** to search everything at once.
- **Filters:** The chips below the search field filter the list, e.g. Hidden or Unskippable achievements.
- **Hide completed:** Shows only what is still open.
- **Show spoilers:**
  - Hidden achievements are redacted until you reveal or unlock them.
  - Click a redaction to reveal one entry, or use the switch to reveal all.
- **Profiles:** Keep separate progress, e.g. per world or per player. Use **Manage** to create, rename, switch or delete them.

## Your progress and backups

Progress is saved automatically in your browser's local storage. It is never uploaded anywhere.

- Every browser keeps its own progress.
- The online demo and a downloaded copy also keep separate progress.
- To move your progress, use **Backup & restore → Export backup** (saves a `.json` file) and **Import backup…** on the other side.
- Export a backup before clearing your browser data.

## Updating the data (for maintainers)

The data comes from pages of the [Abiotic Factor Wiki](https://abioticfactor.wiki.gg) stored in `wiki-source/`.

1. Get the wiki page into `wiki-source/` (subfolders are fine):
   - **Easiest:** `python tools/fetch_wiki_pages.py "Page Title"` downloads it through the wiki's API. Add `--see-also` to also fetch every page linked under "See Also", e.g. `python tools/fetch_wiki_pages.py Antelight --see-also --dir wiki-source/antelights`.
   - **Or by hand:** `F12` → select `<main>` → *Copy outerHTML* → paste it into a `.html` file.
   - The file name does not matter; pages are recognised by their title.
2. Run `python tools/build_data.py`.
   - This needs Python 3 with `beautifulsoup4` and `requests`.
   - It rebuilds `assets/data.js` and downloads new or changed images.
   - Saved progress stays valid, because entries are identified by category and name.
3. Reload the checklist.

**Options:**

| Option | Effect |
|---|---|
| `--no-download` | rebuild the data only, no images |
| `--refresh-images` | download all images again |

**Lab Masks:**
- Location hints come from the wiki page plus `wiki-source/lab-masks-locations.txt`.
- The format of that file: a short area line, then one line per mask, `Colour- where to find it`.
- The pictures of the colours are cut out of the wiki's group screenshot; the positions are in `LAB_MASK_IMAGE` in the build script.

## Credits & licenses

- **Texts:** adapted from the [Abiotic Factor Wiki](https://abioticfactor.wiki.gg) by its contributors, licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). They were shortened and reformatted.
- **Game images:** © Deep Field Games and/or its licensors. They are not covered by this project's licenses.
- **Code:** [MIT License](LICENSE).
- **Details:** see [CREDITS.md](CREDITS.md) and "About & licenses" in the app.

*Abiotic Factor* is a game by Deep Field Games, published by Playstack. This project is not affiliated with or endorsed by Deep Field Games, Playstack or wiki.gg.
