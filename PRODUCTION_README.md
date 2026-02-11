# Production Readme


## Behavior Compatibility Contract

- **Command names are immutable.** Existing Telegram command names (including aliases) must not be renamed, removed, or repurposed in-place.
- **User-facing text freeze.** Existing user-visible strings must remain byte-equivalent unless an explicit, documented versioning change is approved.

This contract is enforced by the docs inventories:
- `docs/COMMAND_CATALOG.md`
- `docs/MESSAGE_FREEZE.md`
