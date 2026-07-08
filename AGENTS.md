# SiliconBench Implementer Instructions

Invoke the fable-mode skill at session start if your environment supports it.

## Bootstrap
```powershell
if (-not $env:SILICONBENCH_VAULT) { throw "SILICONBENCH_VAULT is unset" }
if (-not (Test-Path $env:SILICONBENCH_VAULT)) { throw "Vault path missing" }
git fetch
git status --short --branch
Get-Content $env:SILICONBENCH_VAULT\00-Status\current-sprint.md
Get-Content $env:SILICONBENCH_VAULT\00-Status\blockers.md
Get-ChildItem $env:SILICONBENCH_VAULT\20-Tickets
```

Take the highest-priority `todo` ticket whose `blocked_by` dependencies are satisfied. Work one ticket at a time in worktree `codex/<ticket-id>`.

## Non-negotiables
- Acceptance criteria are literal commands.
- Run acceptance in the pinned Docker image when the ticket says so.
- Paste raw output into the ticket before moving it to `review`.
- Do not change frozen contracts, scoring constants, timeouts, or task scope.
- Do not put private strategy/evidence material into this repo.
