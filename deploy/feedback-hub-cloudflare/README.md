# Cloudflare Workers Builds entrypoint

Connect `jefison-x/BeyondQuant` to two Cloudflare Workers Builds projects. Both use this directory as their root.

| Worker | Build command | Production deploy command |
|---|---|---|
| `byq-feedback-hub` | `npm run cloudflare:build` | `npm run cloudflare:deploy:hub` |
| `byq-feedback-publisher` | `npm run cloudflare:build` | `npm run cloudflare:deploy:publisher` |

Production branch is `main`. Disable non-production branch deployment; if the UI requires a preview command, use
`npm run cloudflare:preview`, which performs a local bundle dry-run and uploads nothing.

Import and deploy Hub first. Configure only the runtime secrets declared in each corresponding Wrangler config. Never put runtime secrets in
Workers build variables, GitHub Actions, `.env`, `.dev.vars`, or this repository.

The Hub serves direct maintainer-password login at `/admin` on its Custom Domain. Production keeps `workers.dev` disabled. The compatible
`BYQ_FEEDBACK_HUB_ADMIN_TOKEN` secret is treated as the password, every password/Bearer attempt passes a per-source Durable Object throttle,
and the console exchanges success for a short HttpOnly session without application-side password storage. Cloudflare Access for `/admin*`
and `/v1/admin/*` is an optional MFA/IdP layer, not a runtime dependency.

The complete Dashboard fields, watch paths, secret map, validation and rollback procedure are documented in
[`../../docs/operations/central-feedback-hub.md`](../../docs/operations/central-feedback-hub.md).
