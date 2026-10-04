# Aegis frontend

The frontend is a responsive public landing page and authenticated action
workspace for Aegis: a consensus-enforced action firewall for autonomous
agents. It uses the supplied gym-promotion
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
The public proof surface and sandbox are available immediately; live operations
use the same-origin backend after wallet sign-in.

## Landing page and app workspace

The root URL is the public landing page. It explains the evidence, consensus,
and receipt model, shows the verified Bradbury proof record, and provides the
public sandbox. `Launch the app` opens the real workspace at `#app`, so users
have a clear handoff from explanation to operation without losing the static
landing page.

The app workspace is wallet-first: a browser wallet signs one short-lived login
challenge, the backend verifies it, and the authenticated control plane opens
automatically. Wallet connection never requests a seed phrase or private key
and does not silently sign a blockchain transaction. The server-only API token
is never exposed to the browser.

## Authenticated action workspace

After wallet sign-in, the action workspace connects to the same-origin backend
session and exposes the same guarded operations as the API: register an
immutable policy version, create an intent, verify a finalized GenLayer
decision transaction, replace evidence during `REPAIR_REQUIRED`, refresh
persisted state, and consume a receipt once. Direct caller-supplied evaluation
is not exposed. The UI does not fabricate provider attestations or claim that
a request succeeded when the backend rejects it.

The GenLayer route is available only for intents created with the exact
contract-compatible binding: the policy's on-chain action hash, address-shaped
agent and recipient, and the target hash used by `submit_intent`. Generic
off-chain demo intents are deliberately rejected rather than treated as
on-chain-authorized.

### First use

1. Select `Launch the app`, then choose `Try a sandbox action` to preview the
   flow without a wallet or transaction.
2. Connect a browser wallet and approve the sign-in message. The app connects
   to its same-origin control plane automatically; no API URL or bearer token
   is entered by the user.
3. Register an immutable policy, or select the policy already registered by the
   backend operator.
4. Create an intent with its evidence. For the GenLayer path, use 20-byte
   `0x` addresses, the policy's on-chain action hash, a target hash, and an
   expiry.
5. Copy the finalized GenLayer transaction hash from the GenLayer explorer
   (not the Aegis intent ID), paste it into the `GenLayer` tab, and verify the
   expected decision. The transaction hash is `0x` followed by 64 hexadecimal
   characters.
6. If the result is `REPAIR_REQUIRED`, replace evidence with the bound agent;
   once authorized, consume the receipt exactly once from the `Consume` tab.

The public proof record does not require a token. It is a verified Bradbury
record and intentionally cannot create tenant events. The server-side bearer
token is never committed or bundled into the frontend.

### Public sandbox

Visitors can select `Try the sandbox` from the landing page or app workspace.
They can describe an example action and watch the
evidence, consensus, and one-time receipt stages without a wallet, token,
transaction, or external request. The result is explicitly labeled as a
simulation. Real tenant operations remain behind the authenticated operator
control plane.

For local browser-to-backend wallet sessions, configure the API with an exact
origin and a session secret:

```sh
AEGIS_API_TOKEN='use-a-secret-token' \
AEGIS_SESSION_SECRET='another-high-entropy-secret' \
AEGIS_ALLOWED_ORIGINS='http://127.0.0.1:5173,https://aegis-genlayer.vercel.app' \
python -m backend.server
```

The production build defaults to the same-origin `/api` route. Local Vite
development defaults to `http://127.0.0.1:8081`. The API token and session
secret belong only in server environment variables; neither belongs in `VITE_*`
build variables or committed files.

## Interaction map

- The landing page explains the product and hands off to `#app` through the
  header, hero, feature card, and final call-to-action.
- The app workspace provides wallet connection, wallet state, sign-in status,
  and the complete authenticated operator console in one place.
- Landing-page controls smoothly scroll to the system, proof, and FAQ sections.
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
- The sandbox opens from the public landing page and app workspace. The
  preview dialog, when used, is local-only: it validates name and email and
  shows an explicit success state; it does not claim to send an email or
  silently call a missing backend.
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
