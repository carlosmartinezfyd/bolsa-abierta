---
version: "alpha"
name: "Bolsa Abierta"
description: "Consulta documental compacta con la apariencia conservada del prototipo existente."
colors:
  primary: "#08796d"
  secondary: "#61747b"
  accent: "#08796d"
  background: "#f5f7f8"
  surface: "#ffffff"
  text: "#17292f"
  muted: "#61747b"
  border: "#dde5e8"
typography:
  h1: {fontFamily: "Segoe UI, Arial, sans-serif", fontSize: "29px", fontWeight: "700", lineHeight: "1.2", letterSpacing: "-1px"}
  h2: {fontFamily: "Segoe UI, Arial, sans-serif", fontSize: "19px", fontWeight: "700", lineHeight: "1.3", letterSpacing: "-0.35px"}
  body: {fontFamily: "Segoe UI, Arial, sans-serif", fontSize: "15px", fontWeight: "400", lineHeight: "1.5", letterSpacing: "0px"}
  label: {fontFamily: "Segoe UI, Arial, sans-serif", fontSize: "12px", fontWeight: "400", lineHeight: "1.5", letterSpacing: "0px"}
rounded: {sm: "7px", md: "9px", lg: "12px"}
spacing: {xs: "6px", sm: "12px", md: "19px", lg: "24px", xl: "38px"}
components:
  button-primary: {backgroundColor: "{colors.primary}", textColor: "{colors.surface}", rounded: "{rounded.sm}", padding: "9px 13px"}
  button-secondary: {backgroundColor: "{colors.surface}", textColor: "{colors.text}", rounded: "{rounded.sm}", padding: "9px 13px"}
  button-accent: {backgroundColor: "{colors.accent}", textColor: "{colors.surface}", rounded: "{rounded.sm}", padding: "9px 13px"}
  card: {backgroundColor: "{colors.surface}", textColor: "{colors.text}", rounded: "{rounded.lg}", padding: "{spacing.md}"}
  input: {backgroundColor: "{colors.surface}", textColor: "{colors.text}", rounded: "{rounded.sm}", padding: "9px 11px"}
  divider: {backgroundColor: "{colors.border}", height: "1px"}
  caption: {textColor: "{colors.muted}", typography: "{typography.label}"}
---

## Overview

Values documented from the restored `web/styles.css`, preserving the approved existing interface. The task changes source evidence and refresh behavior without a visual redesign.

## Colors

Green identifies primary actions and saved rows. Warnings reuse background `#fff7e8`, border `#ecd7a9` and text `#765523`; neutral notices reuse `#eef3f7`. Focus outlines are `3px solid #097dca`.

## Typography

The existing font stack starts with `ui-sans-serif`, system UI and Segoe UI. Table rows use 12px text; metadata uses 10–12px. Preserve readable wrapping for source titles and provenance.

## Layout

Desktop uses a 220px sidebar, a 75px header and a main area up to 1550px wide with 31px by 38px padding. Existing breakpoints are 1180px, 760px and 370px. At 760px navigation becomes a horizontal grid and table rows become compact cards. Filters remain directly accessible.

## Elevation & Depth

Separation primarily uses thin borders. Reuse existing dialogs, notices and panels; no new shadow or elevation system.

## Shapes

Cards use the 12px radius token, buttons and inputs 7px and notices 9px. Status pills retain their existing styling.

## Components

Refresh uses the existing primary button and spinner. Source attempt and success times are displayed separately. Favorite rows are grouped by document and retain dates; counts across documents do not imply current vacancies. Navigation returns keyboard focus to the main content. Links distinguish archived bytes from the official origin.

## Do's and Don'ts

- Preserve the existing CSS and responsive table behavior.
- Reuse notices for partial checks, failures and static snapshot limits.
- Keep original PDF provenance visible, including missing archived copies.
- Do not introduce a new visual direction or imply that a static reload checked official sources.
