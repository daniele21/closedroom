# ClosedRoom product experience contract

ClosedRoom uses a **code-first** design source of truth. `design/ux-contract.json` records durable experience semantics and `design/brand-kit.json` maps semantic brand/motion ownership to the existing React/CSS implementation.

Canonical implementation sources are `frontend/src/components/ui`, page/workspace components, `frontend/src/index.css`, i18n resources and the current logo assets. Existing screenshots under `docs/assets/` are bounded reference views, not a second design system or an automatically current visual-regression baseline.

Approved raster brand artwork lives under `design/assets/brand/`. These assets are intended for presentations, documentation and promotional compositions; they do not replace the canonical SVG logos used by the application.

Meaningful UX/UI changes follow `skills/design-product-experience/SKILL.md` before implementation.
