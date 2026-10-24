#!/usr/bin/env node

import { execFileSync } from 'node:child_process'
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { createHash, randomBytes } from 'node:crypto'

const SCHEMA_VERSION = 'coding-handoff/v1'
const MAX_BODY_BYTES = 32 * 1024
const MAX_CHANGED_FILES = 200
const DEFAULT_TTL_SECONDS = 86_400

function die(message, code = 1) {
  process.stderr.write(`${message}\n`)
  process.exit(code)
}

function parseOptions(argv) {
  const command = argv[0]
  const options = {}
  for (let index = 1; index < argv.length; index += 1) {
    const key = argv[index]
    if (!key.startsWith('--')) throw new Error(`Unexpected argument: ${key}`)
    const value = argv[index + 1]
    if (!value || value.startsWith('--')) throw new Error(`Missing value for ${key}`)
    options[key.slice(2)] = value
    index += 1
  }
  return { command, options }
}

function git(repo, args, { optional = false, buffer = false } = {}) {
  try {
    return execFileSync('git', args, {
      cwd: repo,
      encoding: buffer ? 'buffer' : 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  } catch (error) {
    if (optional) return buffer ? Buffer.alloc(0) : ''
    const detail = error?.stderr?.toString('utf8').trim()
    throw new Error(detail || `git ${args.join(' ')} failed`)
  }
}

function nulList(buffer) {
  return buffer.toString('utf8').split('\0').filter(Boolean)
}

function sanitizeRemote(value) {
  const remote = value.trim()
  if (!remote) return null

  const scp = remote.match(/^(?:[^@]+@)?([^:]+):(.+)$/)
  if (scp && !remote.includes('://')) {
    return `${scp[1]}/${scp[2].replace(/\.git$/, '')}`
  }

  try {
    const url = new URL(remote)
    return `${url.hostname}${url.pathname}`.replace(/\.git$/, '').replace(/\/$/, '')
  } catch {
    return `local/${basename(remote.replace(/\/$/, '').replace(/\.git$/, ''))}`
  }
}

function isCapsuleArtifact(path) {
  const normalized = path.replaceAll('\\\\', '/').replace(/^\.\//, '')
  return normalized === '.contextcapsule' || normalized.startsWith('.contextcapsule/')
}

function captureRepository(repoPath) {
  const requested = resolve(repoPath || process.cwd())
  const root = git(requested, ['rev-parse', '--show-toplevel']).trim()
  const headSha = git(root, ['rev-parse', 'HEAD']).trim()
  const branch = git(root, ['symbolic-ref', '--short', '-q', 'HEAD'], { optional: true }).trim() || null
  const remote = sanitizeRemote(git(root, ['config', '--get', 'remote.origin.url'], { optional: true }))
  const statusEntries = nulList(git(root, ['status', '--porcelain=v1', '-z'], { buffer: true }))
    .filter((entry) => !isCapsuleArtifact(entry.length > 3 ? entry.slice(3) : entry))

  const changed = new Set([
    ...nulList(git(root, ['diff', '--name-only', '-z'], { buffer: true, optional: true })),
    ...nulList(git(root, ['diff', '--cached', '--name-only', '-z'], { buffer: true, optional: true })),
    ...nulList(git(root, ['ls-files', '--others', '--exclude-standard', '-z'], { buffer: true, optional: true })),
  ].filter((path) => !isCapsuleArtifact(path)))
  const changedFiles = [...changed].sort()
  const fingerprintInput = JSON.stringify({
    head_sha: headSha,
    branch,
    status: statusEntries.sort(),
  })

  return {
    remote,
    root_name: basename(root),
    branch,
    head_sha: headSha,
    working_tree: statusEntries.length === 0 ? 'clean' : 'dirty',
    fingerprint: createHash('sha256').update(fingerprintInput).digest('hex'),
    changed_files: changedFiles.slice(0, MAX_CHANGED_FILES),
    changed_files_truncated: changedFiles.length > MAX_CHANGED_FILES,
    captured_at: new Date().toISOString(),
    root,
  }
}

function boundedString(value, field, max = 500) {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a non-empty string.`)
  if (value.length > max) throw new Error(`${field} must be ${max} characters or fewer.`)
  return value.trim()
}

function stringArray(value, field, maxItems = 20) {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.length > maxItems) throw new Error(`${field} must be an array with at most ${maxItems} items.`)
  return value.map((item, index) => boundedString(item, `${field}[${index}]`))
}

function validateReferences(value) {
  const refs = value ?? {}
  if (typeof refs !== 'object' || Array.isArray(refs)) throw new Error('references must be an object.')
  return {
    proofslip_ids: stringArray(refs.proofslip_ids, 'references.proofslip_ids'),
    issues: stringArray(refs.issues, 'references.issues'),
    pull_requests: stringArray(refs.pull_requests, 'references.pull_requests'),
  }
}

function validateVerification(value) {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.length > 20) throw new Error('verification must contain at most 20 items.')
  return value.map((entry, index) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) throw new Error(`verification[${index}] must be an object.`)
    const source = entry.source
    if (source !== 'observed' && source !== 'reported') throw new Error(`verification[${index}].source must be observed or reported.`)
    const observedAt = boundedString(entry.observed_at, `verification[${index}].observed_at`, 64)
    const observedTimestamp = Date.parse(observedAt)
    if (Number.isNaN(observedTimestamp)) throw new Error(`verification[${index}].observed_at must be an ISO timestamp.`)
    if (observedTimestamp > Date.now() + 5 * 60 * 1000) throw new Error(`verification[${index}].observed_at cannot be in the future.`)
    return {
      command: boundedString(entry.command, `verification[${index}].command`),
      result: boundedString(entry.result, `verification[${index}].result`),
      observed_at: new Date(observedAt).toISOString(),
      source,
    }
  })
}

function findSensitive(value, path = 'input') {
  const keyPattern = /(?:password|passwd|secret|token|api[_-]?key|authorization|private[_-]?key)/i
  const valuePatterns = [
    /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
    /\b(?:ghp|github_pat|glpat)-?[A-Za-z0-9_]{20,}\b/,
    /\bAKIA[0-9A-Z]{16}\b/,
    /\bsk-[A-Za-z0-9_-]{20,}\b/,
    /\bBearer\s+[A-Za-z0-9._~+\/-]{16,}\b/i,
    /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/,
  ]

  if (typeof value === 'string') {
    return valuePatterns.some((pattern) => pattern.test(value)) ? path : null
  }
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const found = findSensitive(value[index], `${path}[${index}]`)
      if (found) return found
    }
    return null
  }
  if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (keyPattern.test(key) && child !== null && child !== '' && (!Array.isArray(child) || child.length > 0)) return `${path}.${key}`
      const found = findSensitive(child, `${path}.${key}`)
      if (found) return found
    }
  }
  return null
}

function validateSemanticInput(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Input must be a JSON object.')
  const sensitivePath = findSensitive(input)
  if (sensitivePath) throw new Error(`Possible secret or credential detected at ${sensitivePath}; remove it before creating a capsule.`)

  const ttl = input.expires_in_seconds ?? DEFAULT_TTL_SECONDS
  if (!Number.isInteger(ttl) || ttl < 60 || ttl > 604_800) throw new Error('expires_in_seconds must be an integer between 60 and 604800.')

  return {
    objective: boundedString(input.objective, 'objective'),
    status_summary: boundedString(input.status_summary, 'status_summary'),
    decisions: stringArray(input.decisions, 'decisions'),
    constraints: stringArray(input.constraints, 'constraints'),
    verification: validateVerification(input.verification),
    blockers: stringArray(input.blockers, 'blockers'),
    next_action: boundedString(input.next_action, 'next_action'),
    references: validateReferences(input.references),
    expires_in_seconds: ttl,
  }
}

function validateCapsule(capsule) {
  if (!capsule || typeof capsule !== 'object' || Array.isArray(capsule)) throw new Error('Capsule must be a JSON object.')
  if (capsule.schema_version !== SCHEMA_VERSION) throw new Error(`Unsupported schema_version: ${capsule.schema_version}`)
  boundedString(capsule.capsule_id, 'capsule_id', 128)
  boundedString(capsule.objective, 'objective')
  boundedString(capsule.status_summary, 'status_summary')
  boundedString(capsule.next_action, 'next_action')
  if (Number.isNaN(Date.parse(capsule.created_at)) || Number.isNaN(Date.parse(capsule.expires_at))) throw new Error('Capsule timestamps are invalid.')
  if (!capsule.repository || typeof capsule.repository !== 'object') throw new Error('Capsule repository metadata is missing.')
  for (const field of ['root_name', 'head_sha', 'working_tree', 'fingerprint']) boundedString(capsule.repository[field], `repository.${field}`, 512)
  stringArray(capsule.decisions, 'decisions')
  stringArray(capsule.constraints, 'constraints')
  stringArray(capsule.blockers, 'blockers')
  validateVerification(capsule.verification)
  validateReferences(capsule.references)
  return capsule
}

function markdownText(value) {
  return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

function markdownList(items, empty = 'None recorded.') {
  return items.length > 0 ? items.map((item) => `- ${markdownText(item)}`).join('\n') : empty
}

function renderMarkdown(capsule) {
  const verification = capsule.verification.length > 0
    ? capsule.verification.map((item) => `- **${item.source}:** \`${markdownText(item.command)}\` — ${markdownText(item.result)} (${item.observed_at})`).join('\n')
    : 'None recorded.'
  const repo = capsule.repository
  return `# ContextCapsule handoff\n\n` +
    `- **Schema:** \`${SCHEMA_VERSION}\`\n` +
    `- **Created:** ${capsule.created_at}\n` +
    `- **Expires:** ${capsule.expires_at}\n` +
    `- **Repository:** ${markdownText(repo.remote || repo.root_name)}\n` +
    `- **Branch:** ${markdownText(repo.branch || '(detached)')}\n` +
    `- **HEAD:** \`${repo.head_sha}\`\n` +
    `- **Working tree:** ${repo.working_tree}\n\n` +
    `## Objective\n\n${markdownText(capsule.objective)}\n\n` +
    `## Current status\n\n${markdownText(capsule.status_summary)}\n\n` +
    `## Decisions\n\n${markdownList(capsule.decisions)}\n\n` +
    `## Constraints\n\n${markdownList(capsule.constraints)}\n\n` +
    `## Changed files\n\n${markdownList(repo.changed_files)}\n\n` +
    `## Verification\n\n${verification}\n\n` +
    `## Blockers\n\n${markdownList(capsule.blockers)}\n\n` +
    `## Next action\n\n${markdownText(capsule.next_action)}\n\n` +
    `## References\n\n` +
    `- ProofSlip: ${capsule.references.proofslip_ids.map(markdownText).join(', ') || 'None'}\n` +
    `- Issues: ${capsule.references.issues.map(markdownText).join(', ') || 'None'}\n` +
    `- Pull requests: ${capsule.references.pull_requests.map(markdownText).join(', ') || 'None'}\n`
}

function atomicWrite(path, contents) {
  const temporary = `${path}.tmp-${process.pid}`
  writeFileSync(temporary, contents, { encoding: 'utf8', mode: 0o600 })
  renameSync(temporary, path)
}

function createCapsule(options) {
  if (!options.input) throw new Error('create requires --input <semantic-input.json>.')
  const semantic = validateSemanticInput(JSON.parse(readFileSync(resolve(options.input), 'utf8')))
  const repository = captureRepository(options.repo || process.cwd())
  const createdAt = new Date()
  const capsule = {
    schema_version: SCHEMA_VERSION,
    capsule_id: `cap_local_${randomBytes(10).toString('hex')}`,
    created_at: createdAt.toISOString(),
    expires_at: new Date(createdAt.getTime() + semantic.expires_in_seconds * 1000).toISOString(),
    objective: semantic.objective,
    status_summary: semantic.status_summary,
    repository: {
      remote: repository.remote,
      root_name: repository.root_name,
      branch: repository.branch,
      head_sha: repository.head_sha,
      working_tree: repository.working_tree,
      fingerprint: repository.fingerprint,
      changed_files: repository.changed_files,
      changed_files_truncated: repository.changed_files_truncated,
    },
    decisions: semantic.decisions,
    constraints: semantic.constraints,
    verification: semantic.verification,
    blockers: semantic.blockers,
    next_action: semantic.next_action,
    references: semantic.references,
  }

  const json = `${JSON.stringify(capsule, null, 2)}\n`
  if (Buffer.byteLength(json, 'utf8') > MAX_BODY_BYTES) throw new Error('Capsule exceeds the 32 KB limit.')
  validateCapsule(capsule)

  const outDir = resolve(options['out-dir'] || join(repository.root, '.contextcapsule'))
  mkdirSync(outDir, { recursive: true, mode: 0o700 })
  const jsonPath = join(outDir, 'latest.json')
  const markdownPath = join(outDir, 'latest.md')
  if (existsSync(jsonPath)) copyFileSync(jsonPath, join(outDir, 'previous.json'))
  if (existsSync(markdownPath)) copyFileSync(markdownPath, join(outDir, 'previous.md'))
  atomicWrite(jsonPath, json)
  atomicWrite(markdownPath, renderMarkdown(capsule))

  return { capsule, files: { json: jsonPath, markdown: markdownPath } }
}

function resumeCapsule(options) {
  if (!options.capsule) throw new Error('resume requires --capsule <capsule.json>.')
  const capsule = validateCapsule(JSON.parse(readFileSync(resolve(options.capsule), 'utf8')))
  let current
  try {
    current = captureRepository(options.repo || process.cwd())
  } catch (error) {
    return {
      classification: 'unverifiable',
      discrepancies: [error instanceof Error ? error.message : String(error)],
      capsule,
      safe_to_reuse: ['objective', 'decisions', 'constraints'],
      recheck: ['repository', 'changed_files', 'verification', 'blockers', 'next_action'],
    }
  }

  const mismatches = []
  const stale = []
  if (capsule.repository.remote && current.remote) {
    if (capsule.repository.remote !== current.remote) mismatches.push('repository remote differs')
  } else if (Boolean(capsule.repository.remote) !== Boolean(current.remote)) {
    mismatches.push('repository remote unavailable for comparison')
  } else if (!capsule.repository.remote && !current.remote && capsule.repository.root_name !== current.root_name) {
    mismatches.push('repository root name differs')
  }
  if (capsule.repository.branch !== current.branch) stale.push('branch changed')
  if (capsule.repository.head_sha !== current.head_sha) stale.push('HEAD changed')
  if (capsule.repository.fingerprint !== current.fingerprint) stale.push('working-tree fingerprint changed')
  if (new Date(capsule.expires_at) <= new Date()) stale.push('capsule expired')

  const missingFiles = capsule.repository.changed_files.filter((file) => !existsSync(join(current.root, file)))
  if (missingFiles.length > 0) stale.push(`${missingFiles.length} recorded changed file(s) no longer exist`)

  const classification = mismatches.length > 0 ? 'mismatched' : stale.length > 0 ? 'stale' : 'compatible'
  return {
    classification,
    discrepancies: [...mismatches, ...stale],
    missing_changed_files: missingFiles,
    capsule: {
      capsule_id: capsule.capsule_id,
      objective: capsule.objective,
      status_summary: capsule.status_summary,
      decisions: capsule.decisions,
      constraints: capsule.constraints,
      verification: capsule.verification,
      blockers: capsule.blockers,
      next_action: capsule.next_action,
      references: capsule.references,
      created_at: capsule.created_at,
      expires_at: capsule.expires_at,
      repository: capsule.repository,
    },
    current_repository: {
      remote: current.remote,
      root_name: current.root_name,
      branch: current.branch,
      head_sha: current.head_sha,
      working_tree: current.working_tree,
      changed_files: current.changed_files,
    },
    safe_to_reuse: classification === 'mismatched' ? [] : ['objective', 'decisions', 'constraints'],
    recheck: classification === 'compatible' ? [] : ['changed_files', 'verification', 'blockers', 'next_action'],
  }
}

try {
  const { command, options } = parseOptions(process.argv.slice(2))
  let output
  if (command === 'capture') output = captureRepository(options.repo || process.cwd())
  else if (command === 'create') output = createCapsule(options)
  else if (command === 'resume') output = resumeCapsule(options)
  else throw new Error('Usage: contextcapsule.mjs <capture|create|resume> [options]')
  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`)
} catch (error) {
  die(error instanceof Error ? error.message : String(error))
}
