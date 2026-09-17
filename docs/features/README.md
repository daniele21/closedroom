# Feature documentation

`../features.md` remains ClosedRoom's canonical aggregate feature registry during the 0.8 baseline adoption. Do not duplicate the same behavior here.

Create a bounded file in this directory only when a feature has enough durable behavior, failure semantics, persistence/configuration or verification detail that splitting it materially improves agent context and ownership. Link the new file once from the aggregate registry and keep one canonical owner for each fact.

Feature documentation describes current durable behavior, not implementation progress. When a change alters behavior already described by `../features.md` or a bounded feature document, update that owner in the same change. Do not create a new document for a small feature when code, public contracts, tests and the existing registry already make the behavior sufficiently discoverable.
