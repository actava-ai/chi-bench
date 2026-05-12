# Χ-Bench Logo Design

**Date:** 2026-05-12
**Status:** Approved (pending spec review)
**Reference:** `assets/figures/logo-actava.svg`

## Purpose

Replace the deleted `assets/figures/logo.svg` with a Χ-Bench logo that visually
identifies chi-Bench as an Actava product while standing on its own as a mark.
Used in the README header at width 520 and as a general project mark.

## Lockup

Single-line horizontal lockup: **[colorful Χ mark] + `-Bench` wordmark**.

- The Χ mark functions as the Greek capital chi (Χ) of "Χ-Bench" — it is the
  first letter, not a separate icon.
- `-Bench` sits immediately to the right of the mark on the same baseline,
  cap-height matched to the mark's vertical extent.
- ViewBox ~600 × 200 (3:1). Renders cleanly at the README's 520 px width and
  scales down to favicon/social-avatar sizes (the mark alone remains legible
  when cropped).

## The Χ Mark

A fresh Χ built from scratch using Actava's palette and petal vocabulary — a
family resemblance, not a copy of the Actava cluster.

**Construction:** Two diagonal strokes crossing at the center, each composed of
3–4 organic petal/leaf segments stacked along the diagonal. The petals overlap
slightly where the strokes cross, echoing how Actava's petal clusters layer.

**Stroke A — NW → SE diagonal**
- Anchored deep magenta at the NW endpoint, transitioning through hot pink to
  coral salmon at the SE endpoint.
- Palette: `#991e74` → `#c42475` → `#ff4788` → `#ff827a`.

**Stroke B — NE → SW diagonal**
- Anchored bright pink at the NE endpoint, transitioning through pink to deep
  magenta at the SW endpoint.
- Palette: `#ff0092` → `#ff4491` → `#ff609e` → `#a72d7d`.

**Crossing:** Stroke A passes over Stroke B at the center, with the topmost
petal of B peeking out to suggest interlocking ribbons rather than a flat
overlay.

**Geometry:** Mark occupies a roughly square region (~180 × 180 within the
~600 × 200 viewBox), centered vertically. Diagonal angle ~30° off vertical
(60° off horizontal) so the Χ reads with strong, even arms.

## Wordmark

- Text: `-Bench`
- Color: `#a72d7d` (the Actava deep-magenta wordmark color)
- Weight: heavy/black sans-serif, weight matched to Actava's "actava"
  (visually similar to Helvetica Black / Arial Black)
- Hyphen: same color, hairline thickness, vertically centered on the
  x-height
- Positioned with a small gap (~12 px) to the right of the Χ mark
- Set on the same baseline as the mark's vertical center

## Variants to Produce

Three SVG files written to `assets/figures/`:

1. **`logo.svg`** (recommended, used in README) — the design described above:
   two crossing petal-ribbons with smooth coloration.
2. **`logo-alt-bold.svg`** — sharper, more geometric petals with a stronger
   diagonal axis. Each stroke reads as 3 chunky angular segments rather than
   organic petals. Better legibility at favicon sizes.
3. **`logo-alt-organic.svg`** — looser, flame-like petals with more curvature
   and asymmetry. Closer to Actava's organic feel; more decorative, less
   legible as a Χ at small sizes.

All three share the same lockup, palette anchors, viewBox, and wordmark
treatment — they differ only in the petal geometry of the Χ mark.

## Non-Goals

- No healthcare iconography (cross, pulse line, stethoscope). Decided against
  during brainstorming.
- No benchmark/bar-chart motif. Decided against during brainstorming.
- No full "Χ-Bench" wordmark (the Χ is the mark itself, so writing
  "Χ-Bench" as text would double up). The README's `<h1>Χ-Bench</h1>` already
  provides the textual title beneath the logo.
- No new color palette. Anchors must come from Actava's existing palette.

## Acceptance

- `assets/figures/logo.svg` exists and renders at 520 px width in the README
  without visual distortion or clipping.
- The Χ mark is recognizable as a Χ at the README size and at 64 px.
- The wordmark color and weight visually match `logo-actava.svg`'s "actava".
- Two alternate variants exist alongside `logo.svg`.

## Implementation

The implementation is a single step: hand-author the three SVG files. No
multi-step plan is required.
