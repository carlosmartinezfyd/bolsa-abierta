---
version: "alpha"
name: "Bolsa Abierta"
description: "Consulta documental legible y densa, con identidad tipográfica sobria y procedencia siempre accesible."
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
      fontSize: "19px",
      fontWeight: "600",
      lineHeight: "1.3",
      letterSpacing: "-0.2px",
    }
  body:
    {
      fontFamily: "IBM Plex Sans, Segoe UI, sans-serif",
      fontSize: "14px",
      fontWeight: "400",
      lineHeight: "1.5",
      letterSpacing: "0px",
    }
  label:
    {
      fontFamily: "IBM Plex Sans, Segoe UI, sans-serif",
      fontSize: "12px",
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

A practical reading desk for teachers: precise, calm and recognisable. The October 2026 interface revision prioritises visible results, everyday controls and readable source evidence. It supersedes the earlier instruction to preserve the prototype's appearance.

## Colors

Deep green for actions and active navigation; warm grey-green background and white working surfaces. Text and metadata must meet WCAG AA contrast. Amber identifies limitations or failed/partial checks; a green status never certifies current vacancy availability. Focus uses a clearly visible 3px blue outline.

## Typography

Self-hosted IBM Plex Sans in Regular, Medium and SemiBold, with its original OFL license. No external font requests. Body and row labels are 14px, secondary text and field labels at least 12px. Headings use weight 600. Codes use a system monospace; numbers use tabular figures. At very wide viewports increase the scale, not the gaps. Text wraps instead of being permanently truncated.

## Layout

Desktop: 208px sidebar, 48px context bar, fluid main width with 24–32px margins. Avoid the centred narrow column on large displays. The publication selector and four inline counts share one compact strip; the publication caveat and check summary stay visible, with full provenance available in Sources. Search and all seven filters remain visible. Table data starts early in the first viewport. Compact rows are the default; a comfortable mode adds padding without changing text size. Page size is selectable (25, 50, 100). At 1250px filters wrap; at 900px navigation becomes a top grid and table rows become cards. Mobile controls use 16px text, 44px primary touch targets and no horizontal page overflow.

## Elevation & Depth

Use borders and pale surface changes for hierarchy. Shadows belong to modal dialogs and toasts. Table headings stay visible while scrolling desktop results. Respect reduced motion and keyboard focus; preserve focus when results are replaced.

## Shapes

Buttons and fields have a 5px radius, panels 10px. Small, restrained pills carry semantic labels. No decorative gradients, glass effects or large metric cards.

## Components

Vacancies: publication context, search and visible filters, active filter chips, result summary and sort controls, table and pagination. Sort direction is explicitly labelled Ascendente/Descendente; original document order stays available. Function names open row details. Municipality, centre and codes are distinct table columns on desktop. Favorites remain grouped by source document, even after sorting.

Changes: dates and process identifiers anchor the comparison; filter counts sit inside the category buttons. Acts separate incorporated copies from official announcements. Following leads with saved rows and selected functions; unavailable personal position is secondary. Page headings stand alone: no explanatory subtitle, marketing copy or repeated scope in the sidebar. Notices state only what affects the interpretation of the data. Sources lead with last attempt, last full success, missing publications and documents; technical logs and hashes are expandable. Archived PDF and official origin links are always distinct.

## Do's and Don'ts

- Keep the publication date, limitation on current availability, partial/failure state and missing-document count visible.
- Keep daily filters visible, labels short and sort direction explicit.
- Preserve every original record, duplicate and source reference; display changes never change the source data.
- Avoid totals that combine vacancies from different publications.
- Do not claim a snapshot reload checks official sources.
- Do not use tiny text to gain density, or add analytics, remote assets or paid dependencies.
