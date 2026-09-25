# Security policy

## Reporting a vulnerability

Do not include credentials, private documents, or exploit details in a public issue. Use GitHub's private vulnerability reporting when enabled. If no private reporting channel is available, open an issue requesting one without disclosing vulnerability details. In the private report, include a safe reproduction, affected versions, and impact.

## Supported versions

Security fixes target the latest code on the default branch. Older snapshots are not maintained unless a release explicitly says otherwise.

## Deployment notes

The sample Cloud Run deployment serves a public BYOK API. A public deployment must keep operator Gemini credentials out of request paths, restrict its runtime service account, configure request-size and instance limits, and place rate limiting at a trusted edge. See [the deployment guide](../deploy/README.md#public-service-configuration).
