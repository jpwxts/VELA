---
version: 1
slug: "app-static-index-html"
primary_target: "app/static/index.html"
related_targets: ["app/static/styles.css","app/static/app.js"]
---

# Vela app shell (app/static/index.html)

Scope: the single app screen. Visitor mode: Operate.

Audience and job: someone checking one piece of land. Task: find or draw land on the globe, check a date, then read heat, history, weather and method beside the map. All existing functions stay.

Constraints: plain HTML/CSS/JS, no build step; CesiumJS from a pinned CDN; no ion token; existing element ids and API calls preserved.

## Direction contract

THESIS: A fire atlas you can spin. The globe itself is the drawing: flat sea, land in contour lines, heat as ember dots. Refuses the category default of dark satellite imagery under a stack of grey side panels.

OWN-WORLD: Atlas plate at night (user revision, 2026-11-14). Near-black green shell (#111916), deep sea-green water, dark olive land with fine light-green contour lines, warm off-white text, light teal for selection and primary action, ember reserved for observed heat. Serif display for names and readings, sans for controls, small mono labels only for measurements, dates and coordinates.

STORY: The visitor sees the whole Earth as one plate, turns it to their land, draws it, and reads four separate answers on one card without losing the map.

FIRST VIEWPORT: 64px header with the wordmark only. 60px icon rail with four destinations named in tooltips. The globe fills the rest over a faint star field: search with a magnifier and a pencil Draw button top-left. The legend opens beside its button at the foot of the rail and carries the data credit. A 384px card floats top-right with the start state and the Check my land action.

FORM: Direction pinned by the user's four reference screenshots. Signature move: real terrain drawn as contour lines on a live globe, with spacing that adapts to zoom. seed:088fedbff81543f7

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
