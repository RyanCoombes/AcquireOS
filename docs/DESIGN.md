# Design notes

The brief: bright, clean, easy to use, and not looking like a typical
AI-generated interface.

## What "AI-generated UI" usually looks like

Interfaces produced by AI assistants (Claude included) tend to fall back on
the same defaults. We avoid each one on purpose.

| Common default | What AcquireOS does instead |
|---|---|
| Indigo, violet or blue-600 accent; purple-to-pink gradients | One deep bottle green for actions, a highlighter yellow for "look here", no gradients anywhere |
| Claude's own warm cream background with a terracotta accent and a serif heading | Plain white paper, black ink, no serif, no warm beige |
| Everything inside rounded cards (`rounded-xl`, soft drop shadows) | No cards and no shadows. Sections are divided by hairline rules, like a printed ledger. Corners are square (2px at most on controls) |
| A row of four KPI tiles, each with an icon in a tinted circle | Key numbers sit inline in a single fact line, set in large tabular figures |
| Inter or system font, medium weight everywhere | Schibsted Grotesk (a newspaper typeface), bundled locally, with strong weight contrast and tabular numbers |
| Small uppercase "eyebrow" labels with wide letter-spacing | Sentence-case labels in a muted grey |
| Pill-shaped coloured badges for every status | Status as plain text with a small square marker |
| Lucide icons beside every label; sparkle icon for anything AI | Words, not icons. No sparkles |
| Left sidebar with icon plus label | A single top bar of text tabs with an underline for the current page |
| Generous padding, centred layouts, lots of empty space | Dense, left-aligned tables with full-width rows, built for scanning hundreds of companies |
| Charts from a library with default styling (rounded bars, legends, tooltips) | Hand-drawn SVG small multiples: thin lines, direct labels, no legends, no gridline clutter |
| Dark mode by default, slate-900 | Bright by default: white page, high contrast |

## Principles

1. **Paper, not app chrome.** It should feel like a well-set research
   document you can act on.
2. **Every number shows where it came from.** Estimates say "estimated",
   inferred periods are marked, and every score point has a reason.
3. **Keyboard first.** `/` searches, `j` and `k` move through the list,
   `Enter` opens, `Esc` goes back, `1` to `5` set a rating on a company page.
4. **Your judgement stands out.** Your status, rating and notes are always
   on the right of a company page, set apart from computed data by a
   heavy rule.

## Tokens

| Token | Value | Use |
|---|---|---|
| `--ink` | `#121416` | Text |
| `--ink-2` | `#596067` | Secondary text and labels |
| `--rule` | `#E2E5E8` | Hairlines |
| `--paper` | `#FFFFFF` | Page |
| `--paper-2` | `#F5F7F6` | Toolbar band, table header |
| `--green` | `#0B6A48` | Links, primary actions, good |
| `--yellow` | `#FFE35A` | Highlight, focus, selected row marker |
| `--red` | `#B3261E` | Misses, exclusions, falls |
| `--amber` | `#A15C00` | Partial or uncertain |
