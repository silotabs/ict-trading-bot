# Security Policy

## Supported status

This repository is currently a local paper-trading and shadow-review system. It is not approved for live trading.

## Secrets

Do not commit real credentials or tokens. Keep these in `.env`, a local secret manager, or your shell environment:

- exchange API keys and secrets
- webhook secrets
- operator tokens
- account identifiers
- private runtime URLs

`.env.example` is the only environment file intended for GitHub.

## Reporting issues

For private repositories, open a private issue or contact the repository owner directly. For public repositories, avoid posting exploit details or secret values in public issues.

Include:

- affected file or endpoint
- reproduction steps
- expected safe behavior
- actual behavior
- whether execution eligibility, order submission, risk controls, or secret exposure are affected

## High-risk areas

Changes touching these areas need extra review:

- execution eligibility
- order proposal submission
- risk-control gates
- operator kill switch / pause controls
- private stream and account-aware logic
- webhook authentication
- persistence of execution intents, risk checks, and signal traces
