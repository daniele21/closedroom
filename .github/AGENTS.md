# Shared Mac CI (.github scope)

The versioned source-owned `.github/ci/local-test.sh` is a bounded
deterministic macOS ARM64 check lane executed through
`daniele21/local-runner-infra`. Extend it for fast, representative
source-only contracts; never download models or build/package/sign apps
in this lane. All checks must fail closed if prerequisites or tests fail.

The Terraform-managed `.github/workflows/local-ci.yml` sends the exact
trusted main/dev commit to the central repository through
`repository_dispatch`. **Never** register central Mac runners in
ClosedRoom or use `runs-on: [self-hosted, macOS, ARM64, local-shared]`
in source jobs. Do not dispatch unreviewed feature/fork PR code to
an unisolated personal Mac. Keep source and central token permissions
restricted; never print or store credentials in files or logs.

A successful *dispatch* only proves delivery. Read the
`local-ci/mac` status on the exact source SHA and the central job logs
before claiming a Mac lane PASS. Original preflight/PR/release
checks and required gates remain in force until audited parity;
the initial lane is not packaged-app, TCC or MLX evidence.

Central contract:
https://github.com/daniele21/local-runner-infra/blob/main/docs/integration-guide.md
