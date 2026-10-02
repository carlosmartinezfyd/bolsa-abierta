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

A focused position lookup for teachers, with vacancy search as a secondary workspace. The user's October 2 revision prioritises a calm screen over maximum density. The primary result is one person, one specialty, one explicitly dated published-list rank. Evidence is disclosed on demand.

## Colors

Deep green for actions and active navigation; warm grey-green background and white working surfaces. Text and metadata must meet WCAG AA contrast. Amber identifies limitations or failed/partial checks; a green status never certifies current vacancy availability. Focus uses a clearly visible 3px blue outline.

## Typography

Self-hosted IBM Plex Sans in Regular, Medium and SemiBold, with its original OFL license. No external font requests. Body and row labels are 14px, secondary text and field labels at least 12px. Headings use weight 600. Codes use a system monospace; numbers use tabular figures. At very wide viewports increase the scale, not the gaps. Text wraps instead of being permanently truncated.

## Layout

Desktop: 208px sidebar and a centred working area capped at 1680px. One sticky toolbar contains title, publication date, refresh, search, function, municipality and workload. Secondary filters, saved-only and followed functions live under More filters, with an active count and removable chips. Remove decorative headline totals and redundant status bands. Keep the toolbar and table headings visible at all scroll positions; derive offsets from measured heights, including mobile navigation and refresh feedback. Rows show function, destination, workload and places. Codes, cupo and extraction metadata belong to the record detail. Use comfortable readable rows without a density toggle. At widths up to 900px or heights up to 600px, only navigation stays fixed; filters scroll with the page so they cannot occupy most of the results viewport. The secondary panel is positioned within the viewport and scrolls internally.

## Elevation & Depth

Use borders and pale surface changes for hierarchy. Shadows belong to modal dialogs and toasts. Table headings stay visible while scrolling desktop results. Respect reduced motion and keyboard focus; preserve focus when results are replaced.

## Shapes

Buttons and fields have a 5px radius, panels 10px. Small, restrained pills carry semantic labels. No decorative gradients, glass effects or large metric cards.

## Components

Mi posición: first sidebar item and primary landing action. Centre a working area of at most 780px. Start with a specialty selector grouped by teaching body, a name/list-number search and one submit action. Require explicit confirmation even for a single match. Then show one white card with the person, specialty, a large green ordinal and the date, labelled “Puesto en la lista publicada”. Keep the official list identifier secondary. Store only the chosen opaque row identifier in localStorage. Do not auto-merge people with the same name or number. Source page, calculation, baseline-only coverage and current-availability limitation belong to “Ver detalle”. No fake rank, predicted call date, generic verified badge or available-candidate count. Refresh must distinguish a real source check from reloading the published reference. An unavailable service cannot display an undated cached rank.

Home: a short introductory page at the root URL and `#home`, with a separate horizontal header and no workspace sidebar. State the product plainly: consulting a published-list position and vacancies in Murcia for Secundaria and other bodies. One main action opens Mi posición; three short sections introduce personal lookup, publication comparison and vacancy search. Show a sample drawn only from the current approved publication, with its date and a clear availability limitation; never invent example vacancies or combine dates. Explain official provenance and the independent status once. Use the existing palette and IBM Plex Sans, a balanced 36–60px introductory heading, a 1200px outer width and a single publication panel. Direct links to working views remain available; the brand returns to Home and browser Back works. Do not add explanatory copy to the search workspace.

Vacancies: a persistent search toolbar, one result count, simple sorting and a four-column data table. Municipality and centre share Destination; technical codes remain in the detail. Sort direction is labelled Ascendente/Descendente when applicable. Favorites remain grouped by source document. Refresh feedback stays visible until dismissed and explicitly distinguishes an unchanged official check, a new list, a partial check, a failure and a snapshot-only reload. Never imply a source check happened when the gateway is unavailable.

Changes: dates and process identifiers anchor the comparison; filter counts sit inside the category buttons. Acts separate incorporated copies from official announcements. Following leads with saved rows and selected functions; links to the published position and official Educarm consultation are secondary. Page headings stand alone: no explanatory subtitle, marketing copy or repeated scope in the sidebar. Notices state only what affects the interpretation of the data. Sources lead with last attempt, last full success, missing publications and documents; technical logs and hashes are expandable. Archived PDF and official origin links are always distinct.

## Do's and Don'ts

- Keep the publication date, limitation on current availability, partial/failure state and missing-document count visible.
- Keep search, function, municipality and workload visible; move secondary filters under More filters and expose their active count.
- Preserve every original record, duplicate and source reference; display changes never change the source data.
- Avoid totals that combine vacancies from different publications.
- Do not claim a snapshot reload checks official sources.
- Do not use tiny text to gain density, or add analytics, remote assets or paid dependencies.
