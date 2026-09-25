# Contributing

## Before opening a pull request

- Run the relevant tests. When local regression modules are available, the offline evaluation suite is `python -m unittest discover -s tools/evaluation -p "test_*.py"`.
- Do not commit API keys, cloud credentials, private source documents, translated private documents, generated logs, or local configuration.
- Use synthetic or redistributable fixtures. Describe any test that requires external services or could incur provider charges.
- Keep provider credentials out of test output and exception messages.

## Changes

Explain the behavior change and the checks you ran. Translation and layout changes should include a minimal, redistributable regression fixture when one can demonstrate the issue safely.

Regression modules (`test_*.py`) are local-only under the current workspace policy and are not included in a fresh clone. Keep them on disk for validation; committing tests requires an explicit exception. Frontend validation uses `npm run build` and `npm run lint` from `frontend/`.
