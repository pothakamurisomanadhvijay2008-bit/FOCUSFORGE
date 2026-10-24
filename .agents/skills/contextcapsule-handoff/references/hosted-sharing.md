# Optional hosted sharing

The local capsule is the source artifact. The existing hosted API remains an optional transport and currently requires a ContextCapsule API key for creation.

## Consent and privacy boundary

- Ask immediately before every upload.
- State that anyone with the hosted capsule URL can fetch its contents.
- Run the local secret checks first.
- Do not upload private repository metadata, unpublished issue details, customer data, credentials, environment values, source excerpts, or full diffs.
- Prefer the short default TTL.

## Backward-compatible API mapping

Map the local handoff into the existing API without claiming native `coding-handoff/v1` server support:

- `summary`: `status_summary`
- `decisions`: `decisions`
- `next_steps`: an array containing `next_action`
- `payload`: the bounded local capsule fields needed by the recipient, including `schema_version`
- `refs.receipt_ids`: `references.proofslip_ids`
- `expires_in`: the local TTL, capped by the hosted API

Keep the local JSON. A hosted URL is transport, not the only copy and not proof that the context remains compatible with the recipient's repository.
