# Main Chat Dual Theme Redesign Spec

## Context

The `main` branch currently has a working Ningyu app shell, but the main chat surface feels visually heavier than desired and too close to the entry/register page's paper-book mood. The user prefers the centered conversation experience seen on `codex/search-reliability`: a calm middle writing space, full-screen scenic background, floating side controls, a grounded bottom input, and a stronger sense that the chat itself is the product.

The redesign applies only to the authenticated main chat interface in `frontend/src/app/ningyu/`. Login, registration, onboarding, password reset, auth APIs, and backend behavior are out of scope.

## Goals

- Rework the main chat interface around a centered conversation stage similar to the `codex/search-reliability` screenshot.
- Preserve the existing day/night theme model instead of making the interface night-only.
- Keep all current chat behavior: thread list, new chat, history, tools, support entry, message streaming states, graph/update trail, feedback buttons, and send flow.
- Avoid a full branch overwrite. Use the other branch as a visual reference and integrate selectively into `main`.
- Maintain responsive behavior across desktop and mobile without clipped text, overlapping controls, or unreachable inputs.

## Non-Goals

- Do not redesign the login/register/onboarding pages.
- Do not alter API contracts, authentication, chat streaming, memory, graph trace data, or backend routes.
- Do not remove debug/status affordances that are useful in local development unless they are restyled in place.
- Do not introduce a new UI framework or major dependency.

## Design Direction

The main chat should feel like a quiet writing table inside a soft landscape, not a dashboard and not a landing page. The tone is reflective, companionable, and slightly cinematic.

Day mode:
- Background remains airy and natural, using the current daytime scenic asset.
- The central stage uses translucent warm paper/glass styling rather than the thick notebook sheet used by the entry page.
- Text colors lean deep green/ink, with pale mint and warm off-white surfaces.

Night mode:
- Background uses the current night scenic asset.
- The central stage becomes a dark blue-green translucent panel with subtle ruled lines.
- Message bubbles and controls should resemble the `codex/search-reliability` screenshot: quiet borders, deep navy surface, soft teal accents, and restrained glow.

Both modes share layout, spacing, controls, and interaction patterns. The theme only changes tokens, contrast, and atmosphere.

## Layout

### Overall Shell

`NingyuAppShell` keeps the current full-viewport scenic shell:

- `ningyu-shell` remains the root visual container.
- Background image, wash layer, ambient motion, and day/night switching remain.
- Header remains available but should not dominate the first read of the chat surface. If retained as hover-revealed chrome, it must not cover the chat or input on small screens.

### Central Chat Stage

The central chat stage should become the primary visual anchor:

- Width: approximately `min(100%, 820px-920px)` on desktop.
- Height: fills available vertical space between top breathing room and bottom input.
- Surface: translucent, ruled, lightly bordered, with 8px-16px radius max. Avoid the heavy curled-paper/book-page treatment in the main chat.
- The title/date can remain, but it should be compact and integrated into the top of the stage rather than behaving like a separate hero.
- The message area must preserve scroll behavior and auto-scroll semantics.

Target desktop composition:

- Left floating rail: history and new chat.
- Center: chat stage and messages.
- Right floating rail: tools and support.
- Bottom: fixed-width centered input aligned with the stage.

### Floating Controls

Keep the existing left/right floating controls, but tune them to match the centered stage:

- Controls use compact icon+label pills.
- Day mode: pale translucent controls with green ink.
- Night mode: dark translucent controls with light text and muted teal borders.
- Controls must stay reachable on desktop and collapse cleanly on mobile.

### Input

The input should feel like a calm writing bar:

- Centered and width-matched with the chat stage.
- Bottom anchored within the app shell, not inside a card.
- Textarea remains one-row by default and grows only within safe bounds.
- Send action remains an icon button.
- Disabled/sending states remain visually clear.

## Message Presentation

User messages:
- Align to the right.
- Use a compact bubble, clear "你" meta label, timestamp, and a subtle accent.
- Night mode should resemble the screenshot: transparent dark bubble with fine border and small decorative accent.

Assistant messages:
- Align to the left.
- Use a wider readable bubble with calmer body text and enough line height for Chinese.
- Preserve trace line rendering when present, but make it secondary and quiet.
- Preserve feedback controls below assistant messages.

System/loading/error states:
- Keep `ChatStateMessage`.
- Restyle as compact inline panels within the stage, not large standalone cards.
- Error tone should be visible but gentle.

Graph/update trail:
- Keep `GraphUpdateTrail` behavior.
- Style it as a collapsible-feeling technical trace panel or compact stage section, visually secondary to conversation text.
- It may remain expanded in local/dev behavior, but should not overpower the assistant answer.

## Component Scope

Primary files expected to change:

- `frontend/src/app/ningyu/NingyuAppShell.tsx`
- `frontend/src/app/ningyu/NingyuAppShell.css`

Possible small supporting changes:

- `frontend/src/styles/tokens.css` only if theme variables need consolidation.
- `frontend/src/app/ningyu/immersiveMotion.ts` only if existing ambient timing conflicts with the new layout.

Files not expected to change:

- `frontend/src/app/auth/*`
- `frontend/src/api/*`
- Backend code and database migrations.

## Implementation Approach

Use selective migration rather than wholesale checkout from `codex/search-reliability`:

1. Compare `ChatWorkspace`, `ChatMessage`, `ChatInput`, floating controls, and relevant CSS selectors between `main` and `codex/search-reliability`.
2. Keep `main`'s current TypeScript data flow and behavioral props.
3. Adjust markup only where the visual structure requires it, such as removing heavy paper-specific wrappers or reducing header ornamentation.
4. Rebuild CSS for the chat stage around shared day/night tokens.
5. Preserve existing class names where practical to reduce churn.

## Responsive Behavior

Desktop:
- Stage centered with side controls visible.
- Input centered and stage-matched.
- Chat content should fit without horizontal scrolling.

Tablet:
- Side controls can tuck closer to screen edges.
- Stage width should use viewport padding.
- Header hover behavior must not hide essential actions.

Mobile:
- Side controls should become compact top/bottom action rows or small floating buttons that do not cover messages.
- Stage fills most width with reduced padding.
- Input stays visible and tappable.
- Message bubbles use near-full width with clear left/right distinction.

## Accessibility

- Preserve semantic landmarks and labels: chat workspace, message input, send button, feedback controls.
- Keep keyboard send behavior: Enter submits, Shift+Enter inserts newline.
- Preserve visible focus states for input, send, feedback, floating controls, thread actions, and support/tools.
- Maintain sufficient contrast in both themes, especially night mode secondary text and trace lines.
- Avoid relying on color alone for error/loading/selected states.

## Verification Plan

Run:

- `npm run check` in `frontend/`.
- `npm run build` if typecheck passes and the visual changes touch shared CSS heavily.

Browser verification:

- Desktop viewport around `1440x1000`.
- Mobile viewport around `390x844`.
- Validate day mode and night mode.
- Validate states: empty chat, existing messages, streaming/sending disabled state, error state if easily simulated, graph/update trail with multiple nodes, feedback buttons visible on assistant messages.
- Check that the input does not overlap messages or side controls.
- Check that text in buttons, bubbles, trace lines, and floating controls does not clip.

## Acceptance Criteria

- The authenticated main chat screen visually matches the centered conversation-stage direction from `codex/search-reliability`.
- Day and night modes both look intentional and share the same layout.
- Login/register pages are unchanged.
- Current chat interactions still work: create/send, message rendering, graph updates, feedback, floating controls, support/tools entry.
- Frontend typecheck passes.
- Browser screenshots confirm no blank screen, no major overlap, and no clipped primary text on desktop and mobile.
