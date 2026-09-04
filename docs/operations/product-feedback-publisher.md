# Product Feedback Publisher Runbook

The local direct publisher is an advanced self-hosted compatibility option and remains disabled by default. The normal open-source
path is the ADR-0052 Central Feedback Hub; see `central-feedback-hub.md`. Normal BYQ users never configure a GitHub account, token,
repository, or permission.

## Preferred GitHub App setup

1. Create/install a GitHub App on exactly the target repository with repository `Issues: write` and no Contents, Pull requests,
   Actions, Administration, Secrets, Deployments, or organization permission.
2. Store the App private key outside the repository and mount it read-only into `feedback-publisher` with a local Compose
   override or platform secret mechanism. Set the App id, installation id, in-container key path, and fixed `owner/repo` in the
   ignored deployment environment.
3. Generate a distinct high-entropy `BYQ_FEEDBACK_PUBLISHER_TOKEN` shared only by Backend and publisher. It authenticates the
   internal lease API and is not a GitHub credential.
4. Start with `docker compose --profile feedback-publisher up -d --wait feedback-publisher`. Verify the admin publisher status
   reports the fixed repository, `github_app`, a recent heartbeat, and bounded queue counts.

A fine-grained token limited to the same repository with `Issues: write` may be injected only as
`BYQ_FEEDBACK_GITHUB_TOKEN` when GitHub App installation is unavailable. Do not ask end users for a token.

## Failure handling

- `rate_limited`, `provider_unavailable`, and `transport_ambiguous` enter bounded retry. Every retry first reconciles the exact
  immutable marker, so a timed-out successful create is mapped instead of repeated.
- Authentication, permission, unavailable repository/issues, validation rejection, marker conflict, or six attempts become
  `failed_terminal`; no unbounded loop runs and no fake Issue URL is returned.
- To pause safely, stop only `feedback-publisher`. Feedback drafts, submission, moderation, publication snapshots and outbox
  remain durable. Restart after fixing configuration; expired leases are reclaimed with a higher fence.
- To revoke, stop the service, uninstall/revoke the App or token, and clear the credential from the deployment secret store.
  Never delete outbox/publication rows. Already-created Issues are not modified or closed by BYQ.

## Security checks

The container must remain UID 10006, read-only, all capabilities dropped, with no source/Git/Docker socket/PostgreSQL/DSH
mount or credential. The only allowed connections are Backend internal publication routes and the fixed GitHub API origin.
Required CI uses a loopback fake GitHub server and makes zero real GitHub writes.
