---
name: Vela
description: A fire atlas you can spin. Find or draw land on a contour-line globe and read what satellites recorded there.
colors:
  teal: "#58b9ad"
  teal-deep: "#86d3c8"
  teal-wash: "#1b3531"
  on-teal: "#0b1412"
  ember: "#ee6540"
  ember-wash: "#3b2118"
  sea: "#132b2a"
  land: "#233127"
  contour: "#86a87a"
  sea-ink: "#6aa39b"
  plate: "#0c1311"
  paper: "#111916"
  card: "#171f1c"
  field: "#1e2825"
  line: "#2a3632"
  line-strong: "#3d4c47"
  ink: "#e8ebe1"
  ink-soft: "#b1bbb1"
  ink-faint: "#8e9a91"
  marker-white: "#fffdf8"
typography:
  display:
    fontFamily: "Source Serif 4, Iowan Old Style, Palatino Linotype, Georgia, serif"
    fontSize: "2.125rem"
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: "-0.015em"
  headline:
    fontFamily: "Source Serif 4, Iowan Old Style, Palatino Linotype, Georgia, serif"
    fontSize: "1.875rem"
    fontWeight: 500
    lineHeight: 1.12
    letterSpacing: "-0.012em"
  headline-pane:
    fontFamily: "Source Serif 4, Iowan Old Style, Palatino Linotype, Georgia, serif"
    fontSize: "1.75rem"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Source Serif 4, Iowan Old Style, Palatino Linotype, Georgia, serif"
    fontSize: "1.5rem"
    fontWeight: 500
    lineHeight: 1.15
  title-sentence:
    fontFamily: "Source Serif 4, Iowan Old Style, Palatino Linotype, Georgia, serif"
    fontSize: "1.25rem"
    fontWeight: 500
    lineHeight: 1.25
  section:
    fontFamily: "Source Serif 4, Iowan Old Style, Palatino Linotype, Georgia, serif"
    fontSize: "1.0625rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.003em"
  body:
    fontFamily: "Source Sans 3, system-ui, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
  body-small:
    fontFamily: "Source Sans 3, system-ui, Segoe UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.45
  control:
    fontFamily: "Source Sans 3, system-ui, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.2
  tooltip:
    fontFamily: "Source Sans 3, system-ui, Segoe UI, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.3
  label:
    fontFamily: "Source Code Pro, ui-monospace, Cascadia Mono, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.1em"
  data:
    fontFamily: "Source Code Pro, ui-monospace, Cascadia Mono, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.5
  wordmark:
    fontFamily: "Source Sans 3, system-ui, Segoe UI, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.035em"
  map-place:
    fontFamily: "Source Sans 3, system-ui, Segoe UI, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1
  map-water:
    fontFamily: "Source Serif 4, Iowan Old Style, Palatino Linotype, Georgia, serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0.16em"
rounded:
  badge: "2px"
  cell: "3px"
  control: "4px"
  card: "6px"
  sheet: "14px"
  search: "999px"
spacing:
  tight: "6px"
  control-gap: "8px"
  gap: "16px"
  block: "22px"
  card-pad: "24px"
  rail-width: "60px"
  card-width: "384px"
components:
  button-primary:
    backgroundColor: "{colors.teal}"
    textColor: "{colors.on-teal}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.teal-deep}"
    textColor: "{colors.on-teal}"
  button-ghost:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "44px"
  button-ghost-hover:
    backgroundColor: "{colors.teal-wash}"
    textColor: "{colors.ink}"
  button-follow-up:
    backgroundColor: "{colors.field}"
    textColor: "{colors.teal-deep}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "40px"
  tool:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "42px"
  tool-hover:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
  tool-icon:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    size: "42px"
  tool-pressed:
    backgroundColor: "{colors.teal-wash}"
    textColor: "{colors.teal-deep}"
  input-search:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    rounded: "{rounded.search}"
    padding: "0 12px"
    height: "42px"
    width: "268px"
  rail-item:
    textColor: "{colors.ink-soft}"
    height: "48px"
    width: "60px"
  rail-item-hover:
    textColor: "{colors.ink}"
  rail-item-active:
    backgroundColor: "{colors.teal-wash}"
    textColor: "{colors.teal-deep}"
  tooltip:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.tooltip}"
    rounded: "{rounded.cell}"
    padding: "5px 9px"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "22px 24px 28px"
    width: "384px"
  segment:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "4px 8px"
    height: "42px"
  segment-active:
    backgroundColor: "{colors.teal}"
    textColor: "{colors.on-teal}"
  calendar-day:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    typography: "{typography.body-small}"
    rounded: "{rounded.cell}"
    height: "40px"
  calendar-day-selected:
    backgroundColor: "{colors.teal}"
    textColor: "{colors.on-teal}"
  notice:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.ink-soft}"
    typography: "{typography.body-small}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  map-badge-land:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.badge}"
    padding: "2px 7px"
  map-badge-cell:
    backgroundColor: "{colors.teal-deep}"
    textColor: "{colors.on-teal}"
    rounded: "{rounded.badge}"
    padding: "2px 7px"
  map-tooltip:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.card}"
    rounded: "{rounded.cell}"
    padding: "5px 9px"
---

# Design System: Vela

## Overview

**Creative North Star: "The Night Atlas You Can Spin"**

Vela is one screen in Operate mode: a visitor arrives with one piece of land in mind, turns a globe to it, draws it, and reads four separate answers on a card beside the map. The world is an atlas plate at night. The shell is near-black green, the water is flat deep sea-green, the land is dark olive drawn in fine light-green contour lines, the type is warm off-white, and the only hot colour on the sheet is the ember of a satellite heat detection. The globe is not a picture behind the interface; it is the drawing itself.

The theme is dark only. The user revised the original cream-paper direction to a dark one, and the build declares `color-scheme: dark` with no light branch. The globe is stripped of everything that would make it look like a rendering: no sky, no atmosphere, no sun lighting, no fog. What remains is a flat disc of sea and land on a ground slightly darker than the shell.

The chrome is as quiet as it can be. The header carries only the flame and the wordmark. The rail shows four icons and names them in tooltips. The globe has no reset, zoom or compass controls: it is dragged, scrolled, pinched or turned from the keyboard. Guidance text appears on the plate only while a boundary is being drawn. What is left on the plate is a search field with a magnifier, one pencil and the card; the legend opens from a button at the foot of the rail. Behind the globe the plate carries a faint star field.

**Key Characteristics:**
- One screen: a wordmark-only masthead, a 60px icon rail, the globe plate, a floating detail card.
- Real terrain drawn as contour lines on a live globe, with the interval following the zoom.
- Ember means observed heat. Teal means chosen. Off-white ink means the visitor's own boundary and individual readings.
- Three self-hosted faces from one family: serif for names and readings, sans for controls and body, mono for measurements.
- Depth by tone: the plate is darkest, the shell above it, the card above that, fields lightest. Two shadows only.
- Dark theme only.

## Colors

A night palette of green-blacks and warm off-white with one working accent and one reserved signal: everything is dark green, olive or ink until a satellite sees heat.

### Primary
- **Chart Teal** (#58b9ad): selection, the active rail item's inset bar, primary actions, the selected 5 km square (3px outline with a 10% fill), the selected-marker ring, the focus ring, checkbox and caret colour. It also draws forecast marks: the forecast point's ring and the forecast-day dash in the calendar.
- **Light Chart Teal** (#86d3c8): hover on primary actions, link text, the icon of the active rail item, follow-up button text, the selected-square map badge.
- **Teal Wash** (#1b3531): the quiet hover and pressed tone for every neutral control, and the fill of the active rail item and the selected replay pass.
- **On Teal** (#0b1412): text and marks on a teal fill.

### Secondary
- **Ember** (#ee6540): observed satellite heat. Heat markers on the globe, the heat swatches in the legend, the heat dot under a calendar day. The flame in the wordmark is the same ember and is the only non-data use.
- **Ember Wash** (#3b2118): the fill of a week that recorded burning activity in the weekly history grid.

### Tertiary
- **Night Sea** (#132b2a): water on the globe, as a flat tone.
- **Night Land** (#233127): land on the globe, and the halo behind city names lettered over it.
- **Contour Green** (#86a87a): contour lines, drawn at 50% opacity (40% above 6,000 km camera height).
- **Sea Ink** (#6aa39b): sea and ocean names.

### Neutral
- **Plate Ground** (#0c1311): the darkest tone: the area behind the globe, the fill of informational notices, the edge around reading dots and the gap inside marker rings.
- **Shell** (#111916): the masthead and rail; also the text colour on light tooltips and the land badge.
- **Card** (#171f1c): the detail card and every floating control.
- **Field** (#1e2825): inputs, neutral buttons, calendar days, anything the visitor types into or picks from; also the hover tone of floating tools.
- **Hairline** (#2a3632): dividers and card borders.
- **Strong Hairline** (#3d4c47): control borders.
- **Ink** (#e8ebe1): text, the visitor's land boundary, individual satellite reading dots, and the fill of tooltips and the land badge.
- **Soft Ink** (#b1bbb1): secondary text, mono labels, rail icons at rest.
- **Faint Ink** (#8e9a91): placeholders, control-hover borders, the "checked, no heat" ring.
- **Marker White** (#fffdf8): the 2px ring around a heat dot and the fill of the forecast point, so both separate from the terrain.

### Named Rules
**The Ember Is Heat Rule.** Ember marks what a satellite observed, and nothing else on the working surface. One dot is one 5 km square seen by one satellite; a dot with an ember outer ring is a square seen by two or more. The brand flame is the single exception. Ember is never a button, a warning, a link or a highlight.

**The Ink Boundary Rule.** The visitor's land is drawn in Ink as a 2px dashed line with a 3% ink fill, labelled by an ink badge. It is never teal (that is the selected square) and never ember (that is heat), so the three things on the map can be told apart at a glance.

**The Teal Means Chosen Rule.** Teal is the colour of what the visitor selected or is about to commit: the active rail item, the selected square, the selected day, the primary button. One filled teal button per group of actions, with On Teal text.

## Typography

**Display Font:** Source Serif 4 (with Iowan Old Style, Palatino Linotype, Georgia, serif)
**Body Font:** Source Sans 3 (with system-ui, Segoe UI, sans-serif)
**Label/Mono Font:** Source Code Pro (with ui-monospace, Cascadia Mono, Consolas, monospace)

**Character:** One superfamily in three voices, the way a printed atlas is set: a calm medium-weight serif for names and figures, a plain sans for anything the visitor operates, and a small mono for measurements. All three are self-hosted variable WOFF2 files (Latin and Latin Extended); nothing is fetched from a font service.

### Hierarchy
- **Display** (serif 500, 2.125rem, 1.1, lining figures): the reading itself: a detection count, a fire-weather danger class.
- **Hero figure** (serif 500, 3.5rem, 1.05, lining figures): used once, for the weekly burning-activity percentage in the land summary. When there is no figure the words ("No estimate yet") drop to 1.75rem.
- **Headline** (serif 500, 1.875rem, 1.12; 1.5rem on narrow screens): the place name at the top of the card.
- **Pane headline** (serif 500, 1.75rem, 1.15): the title of the open pane (Burn activity, History, Weather outlook, Research).
- **Title** (serif 500, 1.5rem, 1.15): stat values in the weather grid. A 1.25rem step carries the one-sentence finding for a selected square; a 1.0625rem step carries small figures in week and forecast rows.
- **Section** (serif 600, 1.0625rem, 1.3): block headings inside a pane. Sub-blocks under them use sans 700 at 0.875rem.
- **Body** (sans 400, 0.9375rem, 1.5): running text; lede paragraphs are capped at 60ch. Supporting text is 0.875rem and source stamps 0.8125rem, both in Soft Ink. The credit line inside the legend is 0.75rem.
- **Control** (sans 600, 0.9375rem): button labels; toolbar tools are 500. Tooltips are 600 at 0.8125rem; the phone tab bar's labels are 600 at 0.75rem.
- **Label** (mono 500, 0.75rem, 0.1em, uppercase, Soft Ink): the name of a measurement directly above its value (Temperature, Wind, Rain / 24 h), a date used as a label, and the country and region breadcrumb above the place name.
- **Data** (mono 400 to 600, 0.75rem, no tracking, tabular figures): the boundary's coordinates, map badges, calendar weekday letters.
- **Wordmark** (sans 800, 1.75rem, -0.035em, lowercase): "vela" beside the flame.

### Named Rules
**The Three Voices Rule.** Serif says what a place is called and what was measured. Sans is for anything pressed, typed or read as a sentence. Mono is for a coordinate, a date used as a label, or the name of a measurement. A face never crosses into another's job.

**The Mono Names A Measurement Rule.** An uppercase mono label sits directly above the value it names, or carries the place breadcrumb above the card title. It never introduces a section or decorates a heading; sections are introduced by serif headings alone.

**The Atlas Lettering Rule.** Names on the globe follow print convention: cities in sans 700 at 0.75rem in ink with a land-coloured halo; seas in italic serif 500, uppercase, tracked 0.16em in Sea Ink; oceans one step larger (0.875rem, 0.22em).

## Layout

The page is a fixed two-row grid that fills the viewport exactly (100dvh): a 64px masthead holding only the flame and wordmark, then the workspace. There is no footer. Nothing on the page scrolls except the body of the card.

The workspace is two columns: a 60px rail of four icon tabs (48px tall, 6px apart), then the plate, which takes all remaining space and clips its contents. Everything else floats on the plate:

- **Top-left, 16px in:** the toolbar: the dark search field joined to a 42px magnifier button on its right, with fully rounded outer ends, then the 42px pencil that starts a boundary, 8px apart. While a boundary is being drawn a teal Finish boundary button joins the row and a one-line hint appears beneath it, counting the corners placed. The hint is hidden at all other times.
- **Top-right, 16px in:** the 384px detail card, at most the plate's height minus the two insets. It is hidden on startup and opens after land is selected or a drawn boundary is finished. Clearing the selection hides it again.
- **Bottom-left, 16px in:** the map legend panel, shown and hidden by the legend button at the foot of the rail, so it opens and closes in the same place beside its button. It opens by itself the first time heat markers appear.
- **Behind the globe:** a faint, fixed star field (a seeded sky box of small off-white and pale teal points on Plate Ground) that turns as the globe is turned. Nothing sits at the bottom-right; the map data credit is the last line of the legend panel.

The globe is told which part of the plate the card covers, so the home view and every flight to a place frame the land in the free area rather than under the card.

Inside the card the rhythm is: 24px side padding, 22px between blocks with a hairline and 20px of padding above each new block, 18px and 16px for sub-blocks, 10px between elements inside a block, and 6px to 8px between sibling controls. The card head sets the boundary's four coordinates as a two-by-two mono grid (W and S above E and N, 18px between columns).

**Narrow screens (860px and below).** The masthead drops to 54px. The rail becomes a tab bar under the masthead, 56px tall, with the four sections and the legend button at its end, and here each icon keeps a short 0.75rem label beneath it because touch has no hover; the active marker moves from the left edge to the bottom edge. The card becomes a bottom sheet (full width, at most 52% of the plate, 14px top corners), hidden until land is selected or a drawn boundary is finished. The search field stretches to share one toolbar row with the pencil, tools grow to 44px, and the legend drops from the tab bar above the sheet.

**The Map Stays Rule.** Detail opens beside the map, never instead of it. No pane, dialog or state may cover the whole plate.

**The Quiet Plate Rule.** Nothing stands on the plate that the visitor is not using. Names live in tooltips, guidance appears only during the act it guides, and the globe is moved by hand rather than by buttons.

## Elevation & Depth

Depth is tonal first. Surfaces get lighter as they come forward: Plate Ground behind the globe, the Shell around it, the Card floating on it, Fields inside the card. Hairlines do the rest. Shadow is used only to show that something floats on the plate, and there are exactly two.

### Shadow Vocabulary
- **Control lift** (`box-shadow: 0 1px 2px rgba(0, 0, 0, 0.45)`): every floating control on the plate: tools, search field, legend.
- **Card lift** (`box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35), 0 18px 40px -16px rgba(0, 0, 0, 0.75)`): the detail card and the search results list.
- **Marker separation** (`box-shadow: 0 1px 3px rgba(0, 0, 0, 0.6)` under a 2px Marker White border): heat dots, so they read against contour lines. The two-satellite ring and the teal selection ring are stacked solid `box-shadow` rings: a 3px Plate Ground gap, then ember (to 5px) or teal (to 6px).

### Named Rules
**The Two Lifts Rule.** A surface is either part of the sheet (no shadow) or floating on the plate (control lift or card lift). Nothing inside the card carries a shadow; blocks inside it are separated by hairlines.

**The Lighter Is Nearer Rule.** A surface that sits above another is one tone lighter, never darker. The one deliberate inversion is the notice, which is recessed to Plate Ground inside the card to read as a note set into it.

## Shapes

Corners are barely eased, like trimmed card stock: 4px on every control, 6px on the detail card, 3px on calendar days and tooltips, 2px on map badges. The only large radius is the 14px top edge of the mobile sheet. Circles are reserved for things that are points on the Earth: heat dots, reading dots, the forecast point, boundary corners.

Borders are 1px throughout: Strong Hairline on controls, Hairline on the card and on dividers. A dashed border means "provisional or not the full picture": the visitor's drawn boundary, a week with partial data, a week with none.

Rail tabs are square-cornered and span the rail's full width; the active tab's 3px teal marker is an inset bar on its left edge.

Icons share one grammar: inline SVG on a 20-unit grid, 1.5px strokes with round caps and joins, drawn in the current text colour, with a small solid dot only where a point is meant. Disclosure markers are a 7px chevron drawn from two 1.5px borders, which turns when its block opens.

## Components

### Buttons
Plain and compact, like the keys of an instrument.
- **Shape:** gently eased (4px), 1px border, sans 600.
- **Primary:** Chart Teal fill and border, On Teal text, 44px minimum height, 18px side padding. Used for the one committing action in a group (Check my land, Finish boundary).
- **Hover / Focus:** primary lightens to Light Chart Teal and presses down 1px when active; focus is a 2px Chart Teal outline offset 2px on every interactive element. Transitions are 140ms on background and border.
- **Ghost:** Field fill with a Strong Hairline border and ink text; hover fills with Teal Wash.
- **Follow-up:** the same neutral button at 40px with 0.875rem Light Chart Teal text, for the next step offered inside a result (View fire calendar, Open weather outlook).
- **Small:** 36px, 0.8125rem, for replay and copy controls.
- **Text link button:** underlined Light Chart Teal, 1px underline, for inline changes ("Change").
- **Disabled:** 50% opacity.

### Toolbar tools
- **Style:** Card fill, Strong Hairline border, 42px tall (44px on narrow screens), 14px side padding, control lift, sans 500.
- **Icon tool:** a 42px square with an 18px icon and no visible text. It carries an accessible name and a tooltip below it. Draw area is a pencil.
- **State:** hover goes to Field with a Faint Ink border; a tool that is switched on (the pencil while drawing) takes Teal Wash, a Chart Teal border and Light Chart Teal colour.

### Tooltips
- **Style:** an Ink tag with Shell-coloured text, sans 600 at 0.8125rem, 5px 9px padding, 3px corners, no shadow. It is the one light surface in the system.
- **Placement:** 10px to the right of a rail tab, vertically centred; 8px below a toolbar icon, horizontally centred.
- **Behaviour:** fades in over 120ms after a 350ms hover delay, immediately on keyboard focus. Not rendered on devices without hover. Every control that has one also has a real accessible name.
- **Globe tooltip:** the same Ink tag at weight 400, up to 260px wide, following the pointer over a mark.

### Cards / Containers
- **Corner Style:** 6px; the mobile sheet has 14px top corners only.
- **Background:** Card.
- **Shadow Strategy:** card lift (see Elevation & Depth).
- **Border:** 1px Hairline.
- **Internal Padding:** head 22px 60px 18px 24px (room for the close button), body 22px 24px 28px. The head holds, in order: the country and region breadcrumb in the mono label style, the place name, a one-line summary, and the boundary's coordinates as a two-by-two mono grid. The body scrolls on its own with a thin Strong Hairline scrollbar.
- **Motion:** the card enters in 280ms, fading in from 10px to the right; the sheet from 16px below.
- **Notices:** setup and saved-example notes are Plate Ground boxes with a Hairline border in Soft Ink. They are information, not errors, and stay in neutral tones.

### Inputs / Fields
- **Style:** Field fill, 1px Strong Hairline, 42px tall. The search field is 268px wide and joined to its magnifier button on the right, with fully rounded outer ends. It keeps the placeholder "Enter Location" and the original dark colors and control shadow. Other fields keep a 4px radius. Date and number inputs use tabular figures.
- **Focus:** the 2px Chart Teal outline, drawn inside the edge on the search field.
- **Checkboxes:** native, 16px, tinted Chart Teal, in rows at least 32px tall.
- **Search results:** a Card list under the field with card lift, hairline-separated rows, Teal Wash on hover.

### Navigation
- **Style:** four icon-only tabs in a 60px rail, each 48px tall with a 22px icon in Soft Ink and no fill at rest. The tab's name stays in the markup for assistive technology and is shown in a tooltip to the right.
- **States:** hover is Teal Wash at 60% strength with the icon in Ink; the active tab is Teal Wash with a 3px Chart Teal inset bar on its left edge and a Light Chart Teal icon.
- **Mobile:** a four-column tab bar, icon over a short text label, with the bar on the bottom edge and no tooltips.

### Segmented choices and day chips
- **Style:** equal-width buttons, Field fill with a Strong Hairline border, 42px minimum, 6px apart.
- **State:** hover is Teal Wash with a teal border; the chosen one is solid Chart Teal with On Teal text. Forecast day chips carry the date over the danger class in smaller type.

### Calendar
- A seven-column grid of nearly square days (40px minimum, 3px radius, 5px gaps) with mono weekday letters above.
- History defaults to Monthly, with separate month and year selectors covering January 1990 through the current month, and bounded previous/next arrows. Each 48px day cell shows its date and stored burning-activity percentage. Positive activity uses Ember Wash, measured zero stays on Field, missing estimates have a dashed outline and a dash. Partial estimates retain a dashed outline. Today has a Faint Ink border; the selected day is Chart Teal and keeps readable dark text on hover. Future dates are disabled.
- Below the calendar, show the weighted monthly activity and the number of days with estimates, then the selected day's rate and coverage. A bar chart switches between daily values for the selected month and weighted monthly values for the selected year. Missing periods stay as gaps, and zero is a baseline mark. The vertical axis scales to the available values with explicit percent labels. Chart bars support mouse and keyboard selection; a disclosure supplies the same values as a table.
- Weekly history is a two-column grid of week buttons under mono month labels: Ember Wash for a week with burning activity, a dashed border for partial or unavailable weeks, an inset teal outline for the open week.

### Readings
- **Reading:** a mono label, then the value in the display serif 4px below it.
- **Stat grid:** two columns of label over 1.5rem serif value, each cell opened by a hairline, with an optional 0.8125rem sans note.
- **Fact rows:** a two-column list, Soft Ink term and 600-weight value, for short pairs such as the observation date.

### Disclosures
Hairline-topped rows with the chevron marker and a sans 600 summary; research questions use 700 at 1rem. Technical detail nests inside its answer as a quieter Light Chart Teal disclosure.

### Land summary
The top of the Burn activity pane once land is selected. Three stacked parts, 18px apart.

- **Cutout:** a 672 by 340 canvas on Plate Ground with a 1px Hairline. It copies a freshly rendered globe frame, showing the current map imagery clipped to the land's outline and fitted to the frame, with a 3px Warm Ink outline and ember dots where heat was seen (ringed when two or more satellites saw it). It refreshes when the map switches between atlas and satellite imagery. Place names are left out. A plain filled outline is used while imagery loads or when the globe cannot be captured.
- **Burning activity:** a Soft Ink label naming the week, then the Hero figure: Vela's weekly burning-activity estimate for the week that holds the observation date. It is never called a chance or probability of wildfire. Where weekly history has not been processed it reads "No estimate yet" with the reason beneath.
- **Today at this land:** a strip of three-hour slots on Field fill with a 1px Strong Hairline and 6px corners, four visible at a time, scrolled with two 28px round arrow buttons that sit on the strip's edges. Each slot stacks the time in mono, a drawn weather icon, the temperature in serif 1.5rem and the wind speed in 0.75rem sans. The current slot is washed teal and labelled "Now". A missing value is written as missing, never as zero.

### Legend panel
A 252px panel on Card Surface with a 1px Strong Hairline, opened and closed by the legend button at the foot of the rail. It holds the map key, three layer checkboxes, and a last line of 0.75rem Faint Ink text crediting the map data (Esri, OpenStreetMap contributors, Natural Earth) and CesiumJS. That line is the only place the credit appears, by the user's direction.

### The Globe (signature)
A CesiumJS 1.147.0 globe loaded from the jsDelivr CDN, with no Cesium ion token. Everything it draws comes from keyless Esri services.

- **Basemap:** Esri's light-gray canvas, recoloured in the browser pixel by pixel into Night Sea water, Night Land, fine olive boundary lines and a lighter green coast line.
- **Contours:** terrain from Esri's world elevation service is drawn only as lines, 1px in Contour Green. The interval follows camera height: 20 m below 12 km, 50 m below 40 km, 100 m below 150 km, 250 m below 500 km, 500 m below 1,800 km, 1,000 m beyond. At the two farthest steps a finer second interval (100 m, then 250 m) is added on ground below 1,500 m so that lowland continents are still drawn. The sea-level line is skipped.
- **Lettering:** above 1,500 km the names are set in the page's own faces from a Natural Earth gazetteer, water first, then cities by population (28 when far out, 110 closer), with collisions dropped. A name must face the camera by a clear angle to be shown, so nothing is lettered near the globe's limb or runs off the disc; wide water names need more room than cities. Below 1,500 km Esri's label tiles take over, recoloured to light ink with a dark halo, because they carry every village name.
- **Marks:** heat as ember dots (16px with a Marker White ring, in a 44px target), a second ember ring for two or more satellites, a teal ring for the selected one; individual satellite readings as small Ink dots edged in Plate Ground; the forecast point as a Marker White dot ringed in teal; the land boundary dashed in Ink with Ink corner dots while drafting; the selected square outlined in teal. Badges on the map are small mono tags: Ink with dark text for the land boundary, Light Chart Teal with On Teal text for the selected square.
- **Satellite imagery:** an optional layer from the legend. While it is on, the contours and the authored lettering are switched off.
- **Motion and input:** the globe is dragged, scrolled or pinched; arrow keys turn it and plus and minus zoom. There are no on-screen navigation buttons. Camera flights ease over 1.2 s to a place and 1.4 s home, 0.35 s for a keyboard zoom step, and are instant under reduced motion. Zoom runs from 1.5 km to 40,000 km.
- **Failure:** if the globe cannot load, a single serif sentence on the plate says why.

## Do's and Don'ts

### Do:
- **Do** keep ember for observed heat and the brand flame. If something is not a satellite detection, it is not ember.
- **Do** draw the visitor's land in dashed Ink and the selected square in solid Chart Teal, so boundary, selection and heat never share a colour.
- **Do** put On Teal text on every Chart Teal or Light Chart Teal fill.
- **Do** set names, pane titles and readings in Source Serif 4 at weight 500, controls and sentences in Source Sans 3, and coordinates, label-dates and measurement names in Source Code Pro.
- **Do** float new controls on the plate as Card surfaces with a Strong Hairline border, 4px corners and the control lift, 16px from the plate's edge.
- **Do** make a surface one tone lighter than the one it sits on, and separate blocks inside the card with a Hairline and 20px to 22px of space, not with nested boxes or shadows.
- **Do** use Teal Wash for hover and pressed states on every neutral control, and solid Chart Teal only for the chosen item or the one primary action.
- **Do** give every icon-only control an accessible name and a tooltip, and give it a visible text label wherever there is no hover.
- **Do** keep icons to the shared grammar: 20-unit grid, 1.5px round strokes, current colour.
- **Do** give the globe the card's footprint so the land is framed in the free part of the plate.
- **Do** honour reduced motion: state transitions and camera flights become instant.
- **Do** keep map sources keyless: CesiumJS from the pinned CDN build, Esri basemap, imagery and elevation.

### Don't:
- **Don't** use ember for buttons, links, warnings or emphasis.
- **Don't** add a light theme. The user chose dark, and the build is dark only.
- **Don't** bring back a lit, shaded or atmospheric globe, or make satellite imagery the default basemap. Terrain is lines, not relief shading.
- **Don't** add reset, zoom or compass controls to the globe, a tagline or source tag to the masthead, a footer line, or standing hint text on the plate. The user removed each of them.
- **Don't** put text labels in the desktop rail.
- **Don't** cover the plate with a full-screen panel or modal. Detail opens on the card.
- **Don't** put a shadow on anything inside the card, or invent a third shadow.
- **Don't** use the uppercase mono label to introduce a section or sit above a heading as decoration. It names a measurement or carries the place breadcrumb, nothing else.
- **Don't** set place names or readings in the sans, or controls in the serif.
- **Don't** introduce colours outside the palette for map marks. A new kind of mark gets ink, teal or a neutral tone, and ember only if it is observed heat.
- **Don't** add a Cesium ion token or any map service that needs a key.
