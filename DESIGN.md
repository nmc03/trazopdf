# DESIGN.md - TrazoPDF (Windows, Qt/QSS)

Design contract for the interface. Functional coverage is in `docs/FEATURES.md`.

**Profiles from the design-system-library toolkit used:** `catalog/linear.app/DESIGN.md` (layered surfaces with 1 px borders, a single chromatic accent, focus ring, pill-shaped tabs and selectors, professional tool density), `catalog/raycast/DESIGN.md` (dark surface hierarchy, thin borders, 6 to 10 px radii, command list with a soft active row) and `catalog/figma/DESIGN.md` (canvas tool with a side toolbar grouped by function and a neutral canvas). The accessibility and interaction rules from `skills/web-design-guidelines` were also applied (visible focus, contrast, accessible names, touch targets, `prefers-color-scheme`). Only principles are adapted; no brands, fonts or assets are copied.

## 1. Principles
- Calm neutrals with a single teal accent (primary action, active tool, selection, focus and progress).
- Hierarchy is built with surfaces, 1 px borders and type weight. The only shadow is the page's shadow over the canvas, painted in `canvas.py`.
- Tool rail on the left (with labels or icons only), document in the center and navigation panel on the right. The document is the protagonist.
- No gradients, no emojis, no decoration. Icons are a family of their own, line-style.
- Light and dark themes with the same token names.

## 2. Palette (tokens `@name`; `theme.py` substitutes them before applying the QSS)
| Token | Light | Dark | Use |
|---|---|---|---|
| accent | #0A7A6C | #3FC1AF | Primary, active tool, focus, progress |
| accenthover | #08695D | #5ED0C0 | Primary hover |
| accentpressed | #065248 | #2DA695 | Pressed |
| accentsoft | #DDF0EC | #173C37 | Selection fill and active tool |
| onaccent | #FFFFFF | #04211D | Text and icon on the accent |
| canvas | #E6E9EB | #141819 | Document area background |
| surface0 | #F4F6F7 | #1B2022 | Window, rail, page panel |
| surface1 | #FFFFFF | #22282B | Top bar, fields, menus, cards |
| surface2 | #E9EDEE | #2C3437 | Neutral hover |
| pill | #EEF1F2 | #2A3134 | Background of pill-shaped groups and the search field |
| border | #D9DFE1 | #343D41 | Dividers and decorative borders |
| borderstrong | #848F93 | #7A878C | Field borders (>= 3:1) |
| ink | #1A2225 | #E9EEEF | Primary text |
| inkmuted | #4B575B | #A7B3B7 | Secondary text and resting icons |
| inkdisabled | #8B9599 | #68757A | Disabled |
| danger | #B42318 | #F2796E | Errors and destructive actions |
| shadow | #0B1417 | #000000 | Page and thumbnail shadow |

Contrasts verified by `tests/test_theme.py` in both themes: text >= 4.5:1 on its surfaces (including `inkmuted` on `surface2`, `pill` and `accentsoft`), `onaccent` on `accent` at rest, hover and pressed >= 4.5:1, and `accent` and `borderstrong` >= 3:1 as focus ring and control border.

## 3. Typography (only fonts installed on Windows)
- Family: `"Segoe UI Variable Text", "Segoe UI", Arial`. Headings: `"Segoe UI Variable Display", "Segoe UI"`.
- Sizes in pt to respect Qt's DPI scaling.

| Role | pt | Weight |
|---|---|---|
| title (welcome) | 21 | 600 |
| subtitle | 10.5 | 400 |
| heading (panel, brand) | 10-11 | 600 |
| body | 9.5 | 400 |
| control | 9.5 | 500 |
| section (rail groups) | 8.5 | 600 |
| caption (status, thumbnails) | 8.5 | 400 |

## 4. Spacing, radii and sizes
- 4 px base: 4, 8, 12, 16, 24, 32.
- Radii: controls 8, pills 10, menus and lists 10-12, welcome card 16.
- Top bar: 28 buttons + 2 focus border. Icons 20 (18 inside pills).
- Rail: 240 expanded (min. 224, max. 300) and 56 compact. Tool rows of about 26 px with 18 icons.
- Right panel: 210 by default, min. 176, max. 300; 38 collapsed.
- Page margin on the canvas: 32 scene units per side.

## 5. Icons
- `pdf_editor/icons.py`: 24 px grid, 1.75 px stroke, rounded caps and joins, inline SVG drawn for this project (no external icon package is used).
- Rendered with `QSvgRenderer` at 16, 20, 24, 32, 40, 48 and 64 px and tinted by theme: rest (`inkmuted` or `ink`), hover (`ink`), disabled (`inkdisabled`) and active (`accent` in the checked state).
- Every tool, top-bar action and document action has its icon. Every icon-only button has a `toolTip` and an `accessibleName`.
- When the theme changes, `EditorWindow.apply_icons()` re-tints all icons registered with `bind_icon`.

## 6. States (all controls)
- normal: `borderstrong` border on fields; top-bar and rail buttons have no border.
- hover: `surface2` (inside a pill, `surface1`).
- pressed: `accentsoft`.
- checked/selected: `accentsoft` and `ink` text. On the rail, a 3.5 px `accent` bar is added on the left edge (painted in `RailButton`) and the icon becomes `accent`.
- **focus (keyboard): 2 px `accent` border, always visible. `outline: none` is never used.** When the window opens, no control has visible focus; it appears when Tab is pressed.
- disabled: text and icon `inkdisabled`, no hover.
- The primary button uses an `accent` background and `onaccent` text; its focus uses an `ink` border.

## 7. Components and hooks (`setObjectName`)
| objectName | Description |
|---|---|
| `AppWindow` | Main window |
| `MainToolbar` | Top bar: open, save, print, undo, redo, page navigator, zoom, search |
| `Pill` | Rounded group of related controls (page navigator, zoom) |
| `SearchField` | Search field with leading magnifier (click or Enter searches) |
| `ToolRail` | Left rail (`QScrollArea`); `compact` property when it is icon-only |
| `ModeButton` / `DocButton` | Rail rows (class `RailButton`); `ModeButton` is checkable |
| `DocButton` (Tools group) | Header and footer, Bates, find and redact, optimize, flatten, labels, insert page, stamps, check and compare text; the rail scrolls if the window is short |
| `RailToggle` | Collapses or expands the rail (Ctrl+B) |
| `TextOptions` | Contextual text formatting; if the rail is compact, it expands it for that session |
| `DocumentArea` | Document view (canvas background, page with soft shadow painted in `PageView.drawBackground`) |
| `PagesPanel`, `PagesHeader`, `CollapseButton` | Collapsible right panel |
| `ThumbnailList` | Thumbnails painted by `ThumbnailDelegate`: shadow, page number and `accent` outline when selected |
| `WelcomeView`, `WelcomeCard`, `DropZone`, `RecentList` | Welcome screen; `RecentList` uses `RecentDelegate` (file icon, name and folder) |

## 8. Screens
- **Welcome:** centered card, 600 px maximum, with the application icon, title, short line, "Open PDF" (primary), "Create blank document" (secondary), drop zone and the recent files list when there are files. It scrolls if the window is short.
- **Workspace:** `ToolRail` | `DocumentArea` | `PagesPanel`. At 1024x768 the rail stays expanded and the right panel at 210. The rail scrolls if not all tools fit.
- **View menu:** Fit to width, Find, compact rail (Ctrl+B), page panel (Ctrl+Shift+B) and Theme (System, Light, Dark).

## 9. Theme
- `theme.apply_theme(app, mode)` resolves `system` with `QStyleHints.colorScheme()`, sets the Qt scheme (dark title bar on Windows), installs the palette and QSS, and restarts the icons. It is applied again when the system scheme changes and the mode is `system`.
- The choice is stored in `QSettings` (`theme`: `system`, `light`, `dark`); the default is `system`.
- The spin box and combo box arrows are PNGs generated per theme in the temporary folder (`write_assets`), because QSS does not draw arrows without an image.

## 10. Accessibility and high density
- Everything is keyboard-accessible in logical order: top bar, rail, document, panel. Recent files open with Enter.
- Every icon button has a `toolTip` and an `accessibleName` in English; shortcuts appear in the tooltip.
- Vector icons at several resolutions; tested at 100, 125, 150 and 200%.
- Thumbnails and icons are painted with the screen's `devicePixelRatio`.
- Plain, neutral UI text and no strings embedded in images.

## 11. Rules
- Do: a single accent, tokens instead of loose hex values, state changes per surface and border, focus always visible.
- Don't: long shadows, gradients, emojis, decorative colors, text smaller than 8.5 pt.
