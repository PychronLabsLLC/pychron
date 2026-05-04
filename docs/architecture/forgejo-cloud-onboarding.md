# Forgejo Cloud Workstation Onboarding (M7)

Plan for wiring the Pychron desktop client into the Forgejo + bot-user
workflow shipped in `pychronAPI` M0–M6 + M8.

Single lab per workstation. No multi-lab switching. Re-onboarding to a
different lab is a destructive wipe + redo.

## Server contract (already shipped in pychronAPI)

- `POST /api/v1/forgejo/workstations/ssh-keys` — register SSH public key,
  returns `bot_username`, `fingerprint`, `default_metadata_repo`,
  `ssh_host_alias { alias, real_host, port, known_hosts_line }`.
  Requires API token with scope `workstations:register_ssh_key`.
  Bootstrap and superuser tokens are 403'd (M3).
- `GET /api/v1/forgejo/labs/{name}/default-metadata-repo` — returns
  `repository_identifier`, `ssh_url`, `https_url`, `branch`.
- `GET /api/v1/forgejo/whoami` — token introspection (kind, scopes,
  lab).
- API tokens shaped `pcy_<lab>_<random>`.

## Layout on disk

| Path | Purpose |
|------|---------|
| `~/.pychron/keys/pychron_<host>` | ed25519 private key, 0600 |
| `~/.pychron/keys/pychron_<host>.pub` | public key |
| `~/.pychron/known_hosts` | scoped known_hosts file |
| `~/Pychron/MetaData` | clone of lab default MetaData repo |
| `~/Pychron/projects/<repo>` | per-project DVC clones |

API token lives in OS keyring (`keyring` lib). Lab name and base URL live
in the existing prefs `.cfg`.

## Milestones

### P1 — Settings model + secret storage

- New prefs pane "Pychron Cloud" under existing prefs framework.
- Fields: `api_base_url`, `lab_name`, `api_token`.
- Token stored via OS keyring; never plaintext in `.cfg`.
- On save, ping `GET /api/v1/forgejo/whoami`; reject on 401 and
  surface the returned scopes so the user can confirm the token can
  actually register a key.

### P2 — SSH key lifecycle

New service: `pychron/forgejo/workstation_setup.py`.

- Generate ed25519 keypair at `~/.pychron/keys/pychron_<host>` if
  missing; perms 0600.
- Read public key, POST to `/api/v1/forgejo/workstations/ssh-keys`.
- Persist response: `bot_username`, `fingerprint`, `ssh_host_alias`
  block.
- Append `known_hosts_line` to `~/.pychron/known_hosts`.
- Append SSH host block to `~/.ssh/config` keyed by alias:

  ```
  Host pychron-<lab>
      HostName <real_host>
      Port <port>
      User git
      IdentityFile ~/.pychron/keys/pychron_<host>
      IdentitiesOnly yes
      UserKnownHostsFile ~/.pychron/known_hosts
  ```

- Idempotent: re-running rotates only when the local key is missing or
  the server rejects it (e.g. fingerprint not registered).
- Cross-platform SSH config path: `%USERPROFILE%\.ssh\config` on
  Windows; require OpenSSH for Windows or fall back to embedded git's
  ssh.

### P3 — MetaData repo bootstrap

- After P2, fetch `/api/v1/forgejo/labs/{name}/default-metadata-repo`.
- Clone via `git clone pychron-<lab>:<repository_identifier>.git
  ~/Pychron/MetaData` if not present.
- Replace existing pychron MetaData path resolution to point at this
  clone — single source of truth, no per-experiment metadata copy.
- Pull-on-start policy is configurable in prefs: always / daily / manual.
  Default: daily.

### P4 — DVC repo discovery

- Repo picker in UI: "Open Project" → list of repos under
  `<forgejo_org>` scoped to the configured lab.
- Cache last-used in prefs.
- Clone on first open under `~/Pychron/projects/<repo>`.
- Push/pull via `pychron-<lab>` alias — no per-repo auth.

> **Dependency on pychronAPI:** assumes a `GET
> /api/v1/forgejo/labs/{name}/repositories` endpoint exists. If
> missing, file as M9 follow-up in `pychronAPI` before starting P4.

### P5 — Migration tool for existing labs (NMGRL)

- Wizard: import existing local MetaData and push to lab MetaData repo.
- Detect existing `.git` repos under user data dir, register them via
  `POST /api/v1/forgejo/repositories/register` (or whichever endpoint
  ships) so they appear in the cloud project list.
- Dry-run mode: print plan, no writes.

### P6 — Token rotation, revocation, re-onboarding

- "Re-onboard workstation" button in prefs → re-runs P2, rotates SSH
  key, replaces server-side row.
- "Revoke this workstation" → calls token revoke endpoint; cascade kills
  the SSH key per M3.
- "Switch lab" is destructive: wipes prefs, key, known_hosts entry, and
  `~/Pychron/MetaData` + `~/Pychron/projects/`. Requires explicit
  confirmation. Then re-runs P1–P3 against the new lab.
- Any 401 from the API: prompt for fresh token, do not silently retry.

### P7 — Tests + dogfood on NMGRL

- pytest fixtures stubbing pychronAPI responses for P1–P3.
- Manual QA matrix: macOS / Windows / Linux. Keyring backends and SSH
  config locations differ.
- Roll out one NMGRL workstation at a time; verify the reaper (M8) sees
  no orphans after each.

## Order

P1 → P2 → P3 land as separate PRs, each behind feature flag
`enable_pychron_cloud`. P4–P5 follow. P6 lands alongside P2. P7 runs
continuously.

## Coupling with pychronAPI

- P4 may need a new endpoint
  `GET /api/v1/forgejo/labs/{name}/repositories`. File the ticket in
  `pychronAPI` before starting P4.
- Reaper events (M8) already log SSH key deletions; no client change
  needed.

## Out of scope

- Multi-lab on the same workstation.
- Switching the active lab without wiping local state.
- HTTPS clones — SSH alias is the only supported transport for
  workstation flows.
