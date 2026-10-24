# `coding-handoff/v1`

## Semantic input

Pass a JSON object to the `create` command:

```json
{
  "objective": "Fix the production signup flow",
  "status_summary": "Redirect issue fixed locally; production email remains unverified",
  "decisions": ["Keep the legacy endpoint for compatibility"],
  "constraints": ["Do not expose environment values"],
  "verification": [
    {
      "command": "npm test -- --run",
      "result": "71 passed, 14 skipped",
      "observed_at": "2026-07-19T09:10:20.000Z",
      "source": "observed"
    }
  ],
  "blockers": ["Production email delivery has not been checked"],
  "next_action": "Run the production signup smoke test",
  "references": {
    "proofslip_ids": [],
    "issues": [],
    "pull_requests": []
  },
  "expires_in_seconds": 86400
}
```

The script adds the repository identity, branch, HEAD, working-tree fingerprint, changed files, timestamps, and capsule ID. It rejects likely secrets and bodies larger than 32 KB.

## Verification sources

- Use `observed` only for a command and result actually seen in the current task.
- Use `reported` for a result inherited from another person, agent, document, or unverified capsule.
- Never convert reported deployment or test claims into observed facts.

## Format boundaries

- Keep list items under 500 characters.
- Keep file paths repository-relative.
- Include no full diffs, file contents, logs, transcripts, environment files, tokens, credentials, or personal/customer data.
- Treat expiry as a prompt to recheck state, not proof that the capsule is fresh.
