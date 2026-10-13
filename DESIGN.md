---
version: "alpha"
name: "Bolsa Abierta"
description: "Consulta de vacantes tranquila y directa, con controles persistentes y detalle progresivo."
colors:
  primary: "#09685d"
  secondary: "#546861"
  accent: "#09685d"
  background: "#f4f6f3"
  surface: "#ffffff"
  text: "#20332d"
  muted: "#5c6e66"
  border: "#d9e1db"
typography:
  h1:
    {
      fontFamily: "IBM Plex Sans, Segoe UI, sans-serif",
      fontSize: "28px",
      fontWeight: "600",
      lineHeight: "1.2",
      letterSpacing: "-0.7px",
    }
  h2:
    {
      fontFamily: "IBM Plex Sans, Segoe UI, sans-serif",
      fontSize: "22px",
      fontWeight: "600",
      lineHeight: "1.3",
      letterSpacing: "-0.2px",
    }
  body:
    {
      fontFamily: "IBM Plex Sans, Segoe UI, sans-serif",
      fontSize: "16px",
      fontWeight: "400",
      lineHeight: "1.5",
      letterSpacing: "0px",
    }
  label:
    {
      fontFamily: "IBM Plex Sans, Segoe UI, sans-serif",
      fontSize: "14px",
      fontWeight: "500",
      lineHeight: "1.4",
      letterSpacing: "0px",
    }
rounded: { sm: "5px", md: "8px", lg: "10px" }
spacing: { xs: "4px", sm: "8px", md: "16px", lg: "24px", xl: "32px" }
components:
  button-primary:
    {
      backgroundColor: "{colors.primary}",
      textColor: "{colors.surface}",
      rounded: "{rounded.sm}",
      padding: "8px 12px",
    }
  button-secondary:
    {
      backgroundColor: "{colors.surface}",
      textColor: "{colors.text}",
      rounded: "{rounded.sm}",
      padding: "8px 12px",
    }
  button-accent:
    {
      backgroundColor: "{colors.accent}",
      textColor: "{colors.surface}",
      rounded: "{rounded.sm}",
      padding: "8px 12px",
    }
  card:
    {
      backgroundColor: "{colors.surface}",
      textColor: "{colors.text}",
      rounded: "{rounded.lg}",
      padding: "{spacing.md}",
    }
  input:
    {
      backgroundColor: "{colors.surface}",
      textColor: "{colors.text}",
      rounded: "{rounded.sm}",
      padding: "7px 10px",
    }
  divider: { backgroundColor: "{colors.border}", height: "1px" }
  caption: { textColor: "{colors.muted}", typography: "{typography.label}" }
---

## Overview

A focused position lookup for teachers, with vacancy search as a secondary workspace. The user's October 2 revision prioritises a calm screen over maximum density. The primary result is one person, one specialty, one explicitly dated published-list rank. Evidence is disclosed on demand.

## Colors

Deep green for actions and active navigation; warm grey-green background and white working surfaces. Text and metadata must meet WCAG AA contrast. Amber identifies limitations or failed/partial checks; a green status never certifies current vacancy availability. Focus uses a clearly visible 3px blue outline.

## Typography

Self-hosted IBM Plex Sans; 16px body/forms, 14–15px dense desktop rows, 13–14px secondary labels, 28–32px h1 (24–28px mobile), 20–24px h2, 48–64px ordinal. Essential limitations are normal body text. Text wraps; original spelling stays available. Preserve acronym and Roman numeral casing without inventing missing words or accents.

## Layout

208px desktop sidebar; working area max 1680px, personal card 780px, home 1200px. Spacing 4/8/16/24/32px, mobile margins 16–20px. Main navigation: Mi ficha, Vacantes, Publicaciones, Guardados, Fuentes y cobertura. Comparison is a Vacantes subview; old hashes remain valid. Mobile shows primary links plus a menu naming the selected secondary section. Sticky toolbar only when width and height leave room; no page-wide horizontal overflow at 320px.

## Elevation & Depth

Borders and subtle surface changes for hierarchy; shadows reserved for dialogs. Visible keyboard focus, reduced motion, focus restoration after updates and Escape dismissal.

## Shapes

Buttons/fields radius 5px; panels 10px. Restrained semantic pills. No decorative gradients, metric gauges, motivational banners or tiny text for density.

## Components

Every result distinguishes document type, publication date, origin-check scope and time, incorporation, retained evidence, coverage and availability. Unknown metadata remains unknown. API loading/failure is separate from no results. Failed reload preserves the dated result; missing current identity preserves the remembered opaque ID for retry.

Mi ficha: type/body/course → identity → rank or dated destination → visible limitation → block/habilitations or workload/incorporation → PDF/page and scoped check date → optional methodology. Ordinal counts the document order, never current availability. Maestros belongs to its unique list. Search another, view, remember and forget are separate actions; no identity merging or personal telemetry.

Home: “Listas y vacantes docentes de Murcia”, two immediate actions Buscar mi ficha and Ver vacantes; partial coverage note. Latest incorporated vacancy publication has date, places and records, not arbitrary sample rows. Loading must never claim no documents exist.

Vacantes publicadas: document selector and historical/PDF warning follow the selected document; search/function/municipality/workload plus secondary filters. Centre first, municipality second. Places and records have explicit units. Empty results hide ordering/export/pagination. Detail prioritizes workload and quantity, then evidence, with raw values/codes expandable. Unknown duration is “No extraída; consulta el documento”.

Comparison: compatible earlier/later publications, scoped filters, semantic table with both sources. Disappearance never means adjudication. Preserve duplicate multiplicity. Dates and units are explicit.

Publicaciones: searchable/filterable archive by type, body, course and date, with bounded pagination. Author and portal host are separate. Act/publication dates separately labelled. Calendar is orientative, never a convocatoria.

Guardados: saved rows grouped by publication and followed functions. Useful empty action. Local scope and export contents explicit; no promised external alerts or unsupported restoration.

Fuentes y cobertura: consultable sets and their dates first, gaps by effect, document evidence, then folded technical inventory/versions/hashes/logs. Zero pending always names its scope. Mobile inventory becomes label/value cards. Inventory size is never an official completeness denominator.

Corrections: offer a channel only when the real private destination and responsible party are configured. Never request nominal data in public GitHub issues.

## Do's and Don'ts

- Preserve every source record, duplicate, identifier and date; display formatting never modifies raw data.
- Display the selected document's limitations beside its result, not only in a collapsed panel.
- Distinguish checking an official source from reloading a retained publication.
- Keep technical evidence accessible without letting it dominate the main reading order.
- Avoid invented availability, probabilities, coverage percentages, dates, authors or administrative conclusions.
- No analytics, remote fonts, paid dependencies or fabricated participant tests.
