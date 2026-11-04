# Design notes

## Direction

Dashboard-first and bright: a light grey canvas, white panels with soft
borders, one deep teal accent, and the Geist typeface (bundled locally, so it
works on a LAN with no internet). The app opens on a **Home** dashboard
(headline numbers, best new targets, what changed, trends, next actions),
with the full list, company pages and reports one click away in a left
sidebar.

An earlier "printed ledger" design (white page, hairline rules, newspaper
type) was replaced because it looked dated.

## Still deliberately avoided

Generic AI-generated UI tends to reach for the same things. AcquireOS does
not use:

- purple or indigo accents, or purple-to-pink gradients
- emoji, sparkle icons or "AI" badges
- huge rounded cards (corners here are 7 to 10px) or heavy drop shadows
- glassmorphism, dark mode by default, or centred hero layouts
- charts from a library with stock styling and legends

## Tokens

| Token | Value | Use |
|---|---|---|
| `--canvas` | `#F5F6F8` | Page background |
| `--panel` | `#FFFFFF` | Panels, tables, sidebar |
| `--line` | `#E6E8EC` | Borders and dividers |
| `--ink` / `--ink-2` / `--ink-3` | `#141820` / `#545C69` / `#8A919D` | Text, secondary text, labels |
| `--teal` | `#0E7C6B` | Primary actions, good scores, charts |
| `--teal-soft` | `#E7F4F1` | Selected states, chips |
| `--amber` | `#B45309` | Partial, researching, flags |
| `--red` | `#C8352B` | Misses, dissolved, overdue |
| `--blue` | `#2F62D8` | Contacted, change notices |

## Principles

1. **Every number shows where it came from.** Estimates say "estimate",
   inferred periods are dashed, every score point has a reason.
2. **Scores read at a glance.** Score badges are teal at 70 or more, amber
   from 40, grey below.
3. **Keyboard first.** `/` or Ctrl+K searches, `j`/`k` move through lists,
   `Enter` opens, `Esc` goes back, `1`–`5` rate a company.
4. **Your judgement is separate.** Status, rating, notes and outreach sit in
   their own panel on the right of each company page.
