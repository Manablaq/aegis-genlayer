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
The public proof surface is read-only until an operator connects an authenticated
tenant endpoint in the control plane. The bearer token is held in React memory
for the current tab only; it is never bundled into the build or written to
local storage.

## Operator control plane

The `Control plane` section connects to the backend HTTP API and exposes the
same guarded operations as the API: register an immutable policy version,
create an intent, verify a finalized GenLayer decision transaction, replace
evidence during `REPAIR_REQUIRED`, refresh persisted state, and consume a
receipt once. Direct caller-supplied evaluation is not exposed. The UI does
not fabricate provider attestations or claim that a request succeeded when the
backend rejects it.

For a browser-to-backend session, configure the API with an exact origin:

```sh
AEGIS_API_TOKEN='use-a-secret-token' \
AEGIS_ALLOWED_ORIGINS='http://127.0.0.1:5173,https://aegis-genlayer.vercel.app' \
python -m backend.server
```

The production build defaults to the same-origin `/api` route. Local Vite
development defaults to `http://127.0.0.1:8081`. The backend endpoint and token
are entered interactively in the control plane; neither belongs in `VITE_*`
build variables or committed files.

## Interaction map

- Header and hero controls smoothly scroll to the system, proof, and FAQ sections.
- The three protocol tabs update the detail panel without a page reload.
- The proof card copies the verified contract ID, with an async Clipboard API
  path and a legacy `execCommand` fallback for restricted browser contexts.
- The wallet surface uses the browser's EIP-1193 provider when one exists. It
  listens for account/network changes, shows a connection error instead of
  faking state, supports address copy, and clears the local session on
  disconnect. It never handles seed phrases or private keys.
- FAQ rows are keyboard-accessible accordions.
- The responsive menu opens and closes on small screens and closes after a
  navigation choice.
- “Get protected” and “Start with Aegis” open the local preview dialog. The
  form validates name and email and shows an explicit local-only success state;
  it does not claim to send an email or silently call a missing backend.
- Proof rows are selectable controls that expose the selected lifecycle detail.
  The proof board is explicitly labeled as a verified Bradbury record rather
  than a fabricated live event stream.
- The GitHub icon is the only external navigation and opens the public repo in
  a new tab.

## Browser QA scope

The release check covers desktop and mobile viewport rendering, no horizontal
overflow, accessible landmarks and control names, smooth scroll targets,
protocol tab transitions, FAQ expansion, modal open/close, form submission,
clipboard feedback path, and runtime console health.
