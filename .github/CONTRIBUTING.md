# Contributing

Thanks for your interest in improving Innkeeper! 🎉

## Getting Started
1. Fork the repo and branch from `main`: `git checkout -b feat/your-feature`
2. Create a venv and install dev dependencies:
   ```bash
   python3.12 -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   ```
3. Copy the env template (only needed for the optional `--live` Qwen path):
   `cp .env.example .env`
4. Seed the deterministic demo month: `innkeeper seed --nights 30`

## Before You Open a PR
- `ruff check .` passes (lint).
- `mypy src` passes (type check) — the optional `qwen/live.py` module is
  advisory-only in CI due to upstream SDK overload typing.
- `pytest --cov=innkeeper_audit` passes (404+ tests, 100% coverage).
- `python scripts/verify_offline.py` passes (socket-guarded offline proof).
- Add or update tests for any behavior change, especially anything touching
  the matcher, policy gate, or crypto/signing invariants (see `tests/test_invariants.py`).
- Keep commits conventional (`feat:`, `fix:`, `docs:`, `chore:`).

## Reporting Bugs / Requesting Features
Open an issue using the provided templates. Include repro steps, expected vs.
actual behavior, and environment details.
