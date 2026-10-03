# Local Product Feedback Publisher (Archived)

This page records the retired local direct-to-GitHub publisher path. The local
Python publisher is not part of the current Compose services, CI build targets,
or release image set. Do not use this page to configure or start a local
publisher.

The R3 source change removes future configuration and build paths only. It does
not remove existing Docker images or running deployments, credentials, stored
feedback/publication data, backups, or historical release manifests.

The current feedback route sends accepted Product feedback through the local
`feedback-hub-relay` to the Cloudflare Feedback Hub. Hub moderation and the
private Cloudflare Publisher remain documented in
[Central Feedback Hub operations](central-feedback-hub.md). The
`BYQ_FEEDBACK_PUBLISHER_TOKEN` described there is the Cloudflare Hub/Publisher
service-binding credential; it is not a local Compose or Backend credential.
