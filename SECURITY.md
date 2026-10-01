# Security Policy

ClosedRoom processes sensitive meeting audio, transcripts and generated analysis. Security and privacy reports are welcome.

Do not publish credentials, private recordings, transcripts, API tokens or other sensitive reproduction data in a public issue. Prefer GitHub's private vulnerability reporting/security-advisory flow when available; otherwise contact the repository maintainer privately through their GitHub profile before sharing sensitive evidence.

## Security boundaries

- Local-first processing is the default. Remote ASR/LLM providers are explicit trust-boundary choices and must not become silent fallbacks.
- The local application service binds to loopback by default and preserves session/auth/origin restrictions.
- User audio/transcripts/prompts/generated content stay out of ordinary logs and telemetry by default.\n- Manual call screenshots are local recording artifacts. Capture requires the existing macOS Screen Recording authority, image pixels/OCR are not logged, and choosing a remote ASR/LLM provider does not implicitly authorize screenshot transfer.
- Signing credentials, provider keys and other secrets must remain external to source control and distributable artifacts.
- Temporary native/audio/model resources must be released on failure, cancellation and shutdown when owned by ClosedRoom.

When reporting a vulnerability, include the affected revision/version, platform, minimal reproduction steps and impact. Redact user content and secrets from logs or screenshots.
