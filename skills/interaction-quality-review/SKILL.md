---
name: interaction-quality-review
description: Use after design-product-experience for material ClosedRoom interactions, especially speaker/media review, lists/detail panes, editing, destructive-like corrections, keyboard support and responsive WKWebView. Produces a measurable, code- and evidence-grounded UX/UI review; not a new design system.
---

# ClosedRoom Interaction Quality Review

## Scope and precedence

Start with `skills/design-product-experience/SKILL.md`: user outcome → task model → IA → hierarchy → states → accessibility → implementation → evidence. This skill **complements** it with a concrete interaction/visual QA loop. Follow root/scoped `AGENTS.md`, `design/ux-contract.json`, `design/brand-kit.json`, and local preflight/evidence rules first. Do not create new global tokens, navigation roots or state owners.

Trigger on material changes to a saved Meeting, playback/editor workflow, bulk action, modal, responsive two-pane UI or a request to improve usability. Skip pure copy/spacing fixes and backend-only changes.

## Useful public design references — patterns, not dependencies

- [Anthropic / frontend-design](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md): ground a distinct visual choice in the product's actual subject; reject repetitive generic card grids and ornamentation before fixing information hierarchy.
- [Vercel / web-design-guidelines](https://github.com/vercel-labs/agent-skills/blob/main/skills/web-design-guidelines/SKILL.md): systematic code-based UI/accessibility audit and location-specific actionable findings; use relevant checklist categories and do not require remote fetching at runtime.
- [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill): searchable guidance by **outcome** and stack, critical accessibility/interactions before visual style. Use targeted research, not a wholesale replacement of ClosedRoom's canonical brand/tokens.
- [Apple HIG / split views](https://developer.apple.com/design/human-interface-guidelines/split-views): selected item visibly anchors a detail pane; adapt/stack at narrow window widths. These are macOS conventions, not a reason to insert a second app sidebar.
- [WCAG 2.2](https://www.w3.org/WAI/WCAG22/quickref/): visible/unobscured focus, keyboard controls, statuses that do not rely on color, and comfortable target sizes.

External repositories may have different licenses. Link to references, extract *ideas* and write original product-specific guidance; do not vendor their entire skill, CSS or design systems. Never make success depend on fetching external guidelines. Never send local audio/transcripts to external design tools.

## Review contract (in sequence)

1. **Outcome/task:** state the user job, what counts as done and why the current view fails. Prefer measurable behavior (steps, errors, verification time), not adjectives.
2. **Object model:** identify exact user concepts and backend identifiers that should be hidden. For speaker UI distinguish a person, detected audio cluster, source track, name and transcript utterance. Do not confuse tracks with people or isolated voice with diarized playback intervals.
3. **Critical journey:** `open → locate → listen/inspect → edit/confirm → feedback → verify → undo/recover`; inspect every interrupted or unavailable edge. No screen is justified unless needed by the journey.
4. **Action hierarchy:** exactly one obvious next action in each primary state; frequent action visible, risky contextual, diagnostics disclosed. Count simultaneous choices and input density; prefer focused detail over repeated identical input cards.
5. **Microcopy:** phrase user outcomes (e.g., “Ascolta campione”, “Unisci le voci”) not engine/provider codes; preserve honest status (saved, saving, needs confirmation, audio missing).
6. **Interaction grammar:** mouse/keyboard Enter, Space, Escape, tab and focus return; editing/dirty/saving/saved/conflict; no accidental destructive actions; version-aware undo; media start/stop, single owner, cleanup on unmount/meeting switch.
7. **Media-specific truth:** playing diarized turns is NOT source separation; overlaps may contain multiple voices. Tie every clip to a trustworthy track and absolute timestamp; never fabricate samples or silently fetch cloud content.
8. **Adaptive layout:** wide split-list/detail only if it improves scan speed; narrow single-column anchored selection/expanded detail; compare 1280, 900, 640 CSS px as **test contexts**, not hard-coded breakpoints. Check 200% text scaling, localization and long names; keep controls reachable in a resizable WKWebView.
9. **Visual hierarchy:** use existing semantic colors, Lucide icons and spacing; test one speaker selected, many speakers, unmatched cluster, warning and empty; no decorative waves that imply unavailable audio evidence. Favor normal-case legible labels over tiny tracked all-caps, thick gradients and duplicate borders.
10. **Accessibility:** native button/input semantics, labels for audio sample number and speaker, visible selection/focus, roving focus only if correct, live announcements for async changes; no tooltip-only actions. Respect reduced motion and high contrast.
11. **Evidence:** requirements → owner/tests. Pure logic: unit; persistence and auth: API; assembled meeting UI: browser journey with snapshots/screenshots; material UI integration: required FULL_MEDIA; packaged WKWebView/physical audio/VoiceOver: separate REAL_ENVIRONMENT proof at release. Do not call a screenshot usability proof.

## Focused review output

For any proposed UI surface, capture only the smallest useful artifact in the *active workstream* and eventually the existing UX contract:

- **Before:** 3–6 observable friction points tied to source/screenshot evidence.
- **Design decision:** one critical path, one alternate/risky path, an ASCII wireframe for wide and compact; state what is deliberately hidden.
- **State matrix:** at minimum idle, selected, playing, saving, saved, conflict, unavailable, empty, rollback and navigation-away.
- **Interaction contract:** entry→action→observable result→recovery; exact user copy for confirmations/errors.
- **QA:** one falsifiable test per important promise; map screenshot/DOM assertions and execution environment.
- **Findings:** `P0|P1|P2 · file:line · symptom · user impact · fix · verification`; do not infer source-line precision from a screenshot.
- **Exit:** note unknown/untested aspects, and separate ITERATION source proof from INTEGRATION media proof and RELEASE target-Mac confirmation.

Reject: cosmetic redesign without task improvement, new provider/model settings for ordinary users, nonlocal speaker matching, duplicated playback/store owners, automatic irreversible deletes, or any UI implying voice separation that the audio does not provide.
