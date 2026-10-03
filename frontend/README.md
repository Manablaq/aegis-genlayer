# Aegis frontend

The frontend is a responsive command surface for Aegis: a consensus-enforced
action firewall for autonomous agents. It uses the supplied gym-promotion
landing-page reference as visual direction—dark editorial composition, hard
yellow accents, diagonal geometry, compact navigation, and a high-contrast
conversion path—while using an original Aegis-specific layout and copy.

## Run locally

From this directory:

```sh
npm install
npm run dev
```

The Vite server runs at `http://127.0.0.1:5173/` by default.

## Checks

```sh
npm run typecheck
npm run build
```

The production build is static and can be served by any static host. The page
does not fabricate a backend response: the proof surface displays the verified
Bradbury lifecycle and contract identity already documented in the repository.
The access request form is deliberately local until an authenticated tenant
endpoint is connected.

## Interaction map

- Header and hero controls smoothly scroll to the system, proof, and FAQ sections.
- The three protocol tabs update the detail panel without a page reload.
- The proof card copies the verified contract ID, with an async Clipboard API
  path and a legacy `execCommand` fallback for restricted browser contexts.
- FAQ rows are keyboard-accessible accordions.
- The responsive menu opens and closes on small screens and closes after a
  navigation choice.
- “Get protected” and “Start with Aegis” open the local preview dialog. The
  form validates name and email and shows an explicit success state.
- The GitHub icon is the only external navigation and opens the public repo in
  a new tab.

## Browser QA scope

The release check covers desktop and mobile viewport rendering, no horizontal
overflow, accessible landmarks and control names, smooth scroll targets,
protocol tab transitions, FAQ expansion, modal open/close, form submission,
clipboard feedback path, and runtime console health.
