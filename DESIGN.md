# Visual Direction

TapTune is presented as a workshop field guide: warm paper, ink-black type, cobalt system marks, orange physical signals, and green playback. The page deliberately avoids a generic dark-tech landing page and uses the physical tap-to-play loop as its visual grammar.

## Product UI instructions

Use this document as the source of truth for every TapTune surface, including the Raspberry Pi web UI, documentation, simulator screens, and future product pages. A page should feel like another page in the same workshop field guide, not like a separate SaaS dashboard.

- **Typography:** Load Space Grotesk for expressive headings and labels, DM Sans for readable copy, and DM Mono only for UIDs, URIs, code, timestamps, and system labels. Use tight, editorial heading tracking and generous line-height for body copy.
- **Color:** Use paper `#f4f1e8` as the default canvas, paper deep `#e8e3d5` for secondary surfaces, ink `#182027` for primary text and dark bands, cobalt `#1945e8` for system marks and primary actions, signal orange `#f06328` for physical input and attention, playback green `#20734f` for successful playback states, muted `#5c635f`, and line `#c9c5b9`.
- **Brand wordmark:** Always typeset the product name as `TapTune`, with `Tap` in the surrounding foreground color and `Tune` in cobalt `#1945e8` on light surfaces. Keep both parts in the same font, weight, size, and baseline; color is the only distinction. Pair the wordmark with the orange concentric tap mark when space permits.
- **Composition:** Prefer a centered `1160px` shell, visible rules, small uppercase mono section indexes, asymmetrical editorial layouts, and generous vertical spacing. Organize functional pages as a field guide: a clear title, a short explanation, a working surface, then inspectable records or next steps.
- **Surfaces:** Prefer flat paper, ink, cobalt, or orange blocks with 1px rules. Avoid gradients, glassmorphism, large rounded cards, excessive shadows, and generic dashboard chrome. Small square corners or no radius are the default; use a modest radius only where it improves an input control.
- **Imagery:** Combine honest, credited product photography with purpose-built technical drawings. Photograph hardware close enough to reveal materials, traces, ports, and wear; avoid generic lifestyle stock. Frame photos as editorial evidence with square corners, visible captions, and restrained cobalt/orange annotations. Use diagrams for signal flow and architecture, never to imitate a photograph. Every image needs explicit dimensions, useful alternative text, and attribution when required.
- **Product language:** Talk about tags, taps, playback, physical input, handoffs, and the signal path. Keep labels concrete and friendly. Show technical values as inspectable system details rather than hiding them behind decorative UI.
- **Controls:** Buttons use the existing `.button` language: compact, bold, rectangular, and high-contrast. Inputs use paper-white surfaces, ink borders, and mono text for identifiers. Quick actions may use outlined controls, but they should still look like field-guide tools rather than pills.
- **Status:** Use orange for attention and input, green for healthy playback or saved state, and cobalt for system information. Status must be understandable through text as well as color.
- **Interaction:** Links and buttons need explicit hover and `:focus-visible` states. Keep motion limited to short color/position changes and honor `prefers-reduced-motion`.
- **Responsive behavior:** Preserve the reading order on narrow screens. Collapse columns into one flow, keep controls full-width when useful, and never let UIDs or URIs overflow the viewport.

When adding a new surface, start from the tokens and patterns in `docs/styles.css` instead of inventing a new palette or component language.

## Spotify music browser

The music browsing/search section is an intentional, user-requested exception
to the paper field-guide surface. Scope its Spotify-inspired styling to
`.spotify-browser`: near-black `#121212`, charcoal `#1f1f1f` cards, white text,
secondary text `#b3b3b3`, and green `#1ed760` selection actions. Use rounded
search fields and collection chips. Saved albums, playlists and recent albums
use an artwork-led grid (two columns on phones) with uncropped artwork.
Search uses one input and compact lists grouped by albums, playlists, songs
and podcasts, with small square thumbnails and 44px minimum action targets.
Keep visible Choose/Selected labels,
keyboard focus, and an Open in Spotify link. Do not add pretend playback
controls: choosing music prepares a tag, not a listening session.

This is TapTune's own implementation of familiar music-browser patterns, not
Spotify's proprietary component library. The outer page, connection notices,
tag-writing steps and advanced UID form retain TapTune's established style.

## Local task pages

Keep the main flow short: choose music, write the tag. Do not repeat titles
in explanatory paragraphs. Connection details, reader setup, manual UID
mapping and log metadata use expandable Help/Details sections; preserve
the distinction between demo music and a live Spotify account.

Writing feedback is an inline panel with a distinct icon, a short heading,
the necessary next step and the tag UID when known. Use different shapes
for waiting, verified success, failure and cancellation, not color alone.
An unknown outcome after a connection failure must say so and offer Check
status rather than enabling another write. Keep overwrite warnings,
reader placement and timeout guidance visible at the relevant step.

The activity page leads with search, filters and chronological messages.
Retention, UTC timestamps and the TapTune-only diagnostic scope belong in
About this log. Raw tag values, resolved URIs and components remain
inspectable in each row's Details.
