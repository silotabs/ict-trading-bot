# Changelog

## Unreleased

### Added

- Root GitHub README with quickstart, safety posture, repo map, and pre-push checklist.
- GitHub push checklist under `docs/`.
- Contribution and security policy docs.
- GitHub Actions CI workflow for backend and frontend checks.
- EditorConfig and Git attributes for cleaner cross-platform commits.

### Fixed

- Made 4H bias inference resilient when a DRT summary contains `liquidity_event: null`.

### Repository hygiene

- Prepared the repo to exclude local secrets, macOS metadata, build artifacts, runtime state, and exported `.git/` history from the cleaned handoff archive.
