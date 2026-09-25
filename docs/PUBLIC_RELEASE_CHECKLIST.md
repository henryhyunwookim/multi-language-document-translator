# Public release checklist

Publishing source and inviting visitors to a hosted translation service are separate decisions. The source publication checks below do not certify a deployment's storage, credentials, or abuse controls.

## Clean publication copy (2026-09-25)

The publication repository is `henryhyunwookim/multi-language-document-translator`. It is an independent repository populated from reviewed source files, with a new root commit. It is not a fork and does not inherit the development repository's branches, pull requests, commit history, or retained document objects.

The original development repository was renamed to `multi-language-document-translator-private-history` and archived privately, pending permanent deletion with the required GitHub account permission. The clean publication repository took the original name. Repository identity and clean history were preserved during the rename; the historical `reference/` tree and private document history were not imported. Private local recovery copies remain excluded from Git and build uploads.

Do not merge, mirror-push, or import old development history into the publication repository. Future changes should be reviewed source changes committed on top of its clean history. Local recovery copies and release administration scripts under `tmp/` are excluded from Git and build uploads.

## Source publication checks

- Export only the reviewed Git tree. Exclude local documents, translated outputs, environment files, credential files, agent state, caches, and local test fixtures.
- Scan the complete publication history with Gitleaks, with credential values redacted in reports. Inspect the tracked paths and binary assets separately; a secret scanner does not assess document confidentiality or ownership.
- Verify that neither `reference/` nor `output_verification/` appears in the publication repository's history and that the old affected commit is unavailable through its GitHub API.
- Audit Python requirements and the full npm dependency tree. Recheck before publication because advisories can change.
- Run the local backend regression suite, frontend lint, and frontend production build. The GitHub workflow also performs dependency audits, a full-history secret scan, and backend startup/route smoke checks.
- Review the final diff. The source includes a security policy and privacy documentation. No license has been selected; public visibility alone does not grant reuse rights.
- Enable GitHub private vulnerability reporting when making the publication repository public. Never restore the old development history into this repository.

## Security maintenance

- `.github/dependabot.yml` checks Python, npm, and GitHub Actions dependencies weekly.
- `.github/workflows/security.yml` runs on pushes to `main`, pull requests, manual dispatch, and a weekly schedule. Workflow permissions are read-only; checkout credentials are not persisted. Actions and the secret scanner are pinned, and the scanner archive is verified by checksum.
- Frontend container builds use `npm ci` with the reviewed lockfile. Both Docker contexts exclude credentials and local configuration.
- Local regression modules remain local under the workspace policy. Run them with `python -m unittest discover -s tools/evaluation -p "test_*.py"` when available.

## Application protections

- Gemini translation and model discovery require the caller's own API key. Cloud Run never falls back to the maintainer's Gemini secret. The optional `ALLOW_SERVER_GEMINI_KEY=true` switch is honored only outside Cloud Run for private local development.
- Diagnostic log and cloud-console endpoints are not exposed. The UI's downloadable log contains only activity held in that browser session.
- Upload bodies are bounded, model discovery does not write a caller's model list into shared storage, and the API limits requests per client per instance.
- Backend Cloud Run deployment is capped at one instance and eight concurrent requests. Increase those limits only after moving durable jobs to shared storage and setting a project budget/alert.
- Job workers start and stop through FastAPI's lifespan handler, including recovery of queued jobs on startup.

## Before enabling broader public traffic

1. Run `deploy/setup-runtime-identity.ps1 -ProjectId <project>` (or the `.sh` equivalent) and verify that the `translator-runtime` service account has only bucket-scoped object access. The deployer needs `roles/iam.serviceAccountUser` on that identity.
2. Deploy the patched backend and frontend. Verify that `/logs`, `/logs/download`, `/cloud-links`, and `/cleanup/...` are unavailable and that Gemini requests without caller keys are rejected.
3. Configure an external Application Load Balancer with Cloud Armor rate limits for translation and upload routes. Restrict Cloud Run ingress to the load balancer and disable the default `run.app` URL so clients cannot bypass edge policy. The in-process limiter is a fallback, not distributed abuse control.
4. Set and monitor Cloud Run instance, concurrency, request-timeout, and budget limits. The API accepts up to 64 MiB per uploaded file and up to 256 MiB total in a batch.
5. Confirm the output bucket has an explicit short retention/lifecycle rule for `document-translator/outputs/`; do not rely on client cleanup requests.
6. Review bucket IAM and access mode. The runtime needs object read/write/delete access; public visitors should not receive bucket access.
7. Review data-handling text and provider terms for the intended audience. Do not invite confidential documents until log retention and storage expiration have been verified in the deployed project.

Past deployment checks apply only to the revisions checked at that time. Source changes and passing local checks do not establish live deployment status or translation quality with a real provider account.
