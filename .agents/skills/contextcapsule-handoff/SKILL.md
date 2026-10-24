---
name: contextcapsule-handoff
description: Create or resume a compact, repository-aware coding handoff between Codex, Claude Code, Cursor, or another coding agent. Use when a task is pausing, switching agents or sessions, approaching context limits, or resuming from a ContextCapsule JSON file. Capture decisions, constraints, verification, blockers, changed files, and the next action without storing transcripts, full diffs, secrets, or unverified completion claims.
---

# ContextCapsule Handoff

Use a local `coding-handoff/v1` capsule as the primary artifact. Treat hosted sharing as an explicit, public-by-link option rather than a first-run requirement.

## Choose the workflow

- Create a handoff when work is pausing or moving to another coding agent.
- Resume a handoff when the user supplies a local capsule or explicitly requests continuation from one.
- Do not use this skill as long-term memory, a transcript exporter, an event log, or a substitute for repository inspection.

## Create a handoff

1. Confirm the repository root and run:

   ```bash
   node <skill-dir>/scripts/contextcapsule.mjs capture --repo <repository-path>
   ```

2. Gather only missing semantic context:
   - objective and current status;
   - decisions and constraints;
   - observed or reported verification;
   - blockers;
   - exact next action;
   - optional ProofSlip IDs, issues, and pull requests.
3. Read `references/coding-handoff-v1.md` and prepare the small semantic input JSON it defines.
4. Never include full diffs, source archives, transcripts, environment values, credentials, tokens, customer data, or large source excerpts.
5. Ask for approval before writing `.contextcapsule/` or changing any ignore file.
6. After approval, run:

   ```bash
   node <skill-dir>/scripts/contextcapsule.mjs create \
     --repo <repository-path> \
     --input <semantic-input.json> \
     --out-dir <repository-path>/.contextcapsule
   ```

7. Report the two created files, their expiry, and any working-tree caveat. Do not commit them unless the user explicitly asks.
8. Upload only when explicitly requested. Read `references/hosted-sharing.md` first and warn that current hosted capsules are public to anyone with the URL.

## Resume a handoff

1. Confirm the intended repository. Do not assume the current directory is correct.
2. Run:

   ```bash
   node <skill-dir>/scripts/contextcapsule.mjs resume \
     --repo <repository-path> \
     --capsule <capsule.json>
   ```

3. Present the classification before relying on the capsule:
   - `compatible`: repository identity, branch, commit, and bounded working-tree fingerprint match;
   - `stale`: the repository or capsule age changed and volatile facts need rechecking;
   - `mismatched`: the capsule describes a different repository;
   - `unverifiable`: repository or capsule state could not be checked.
4. Reuse objective, decisions, and constraints only as appropriate. Recheck changed files, verification, blockers, and next action when the report says so.
5. Treat completion and deployment statements as claims unless a referenced ProofSlip independently verifies them.
6. Inspect the live repository before editing. Never overwrite current work merely because the capsule describes an older state.

## Output

Conclude with:

- compatibility classification and discrepancies;
- objective and status;
- decisions and constraints;
- current changed-file and verification state;
- blockers;
- ProofSlip evidence, clearly separated from claims;
- the next safe action.
