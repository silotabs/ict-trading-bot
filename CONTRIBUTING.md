# Contributing

This project is safety-gated. Treat every change as if it could affect operator trust, even when it looks like a small refactor.

## Development rules

- Keep `verified_paper_trade` as the only execution-eligible decision unless a separate documented promotion process approves a change.
- Do not enable live trading, auto-execution, or broker-facing behavior by default.
- Add or update tests for every logic, storage, risk-control, or API behavior change.
- Update the relevant dossier/runbook when a behavior or stage assumption changes.
- Never commit `.env`, credentials, database files, generated build folders, or local stack state.

## Local checks

Backend:

```bash
python -m pytest -q
```

Frontend:

```bash
cd web
pnpm test
pnpm build
```

## Pull request checklist

- Tests pass locally.
- No secrets are staged.
- Runtime defaults remain conservative.
- Risk-control, readiness, and execution-state behavior are documented when touched.
- Stage wording still matches the Stage 6 / Stage 7 docs unless the PR is explicitly a stage-promotion PR.
