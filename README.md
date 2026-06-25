# Personal Ops Dashboard

A local dashboard for a personal OpenClaw agent system.

It turns the current machine state into one inspectable HTML page:

- OpenClaw gateway/node/service health
- active tasks and TaskFlow audit state
- recent sessions and context pressure
- cron schedule snapshot
- pending approvals snapshot
- local repo dirty/clean status
- latest GitHub workflow runs for tracked repos
- memory note freshness

The dashboard is intentionally local-first. It can include private operational context, so generated dashboard output is ignored by git.

## Quick Start

```bash
python3 scripts/personal_ops_dashboard.py generate --output dashboard
open dashboard/index.html
```

Install the macOS refresh agent:

```bash
scripts/install_macos_launch_agent.sh
```

That installs a LaunchAgent that regenerates the dashboard every five minutes and at login.

On macOS the LaunchAgent runs from a runtime copy under
`~/.openclaw/personal-ops-dashboard`, not directly from `Documents`. That avoids
TCC/privacy friction for background services while keeping this repo clean.

## Configuration

Edit `ops-dashboard.json` to choose:

- repositories to scan locally
- GitHub repositories to check for workflow status
- memory files to watch
- dashboard refresh metadata

## Notes

- The generator never writes secrets into the repo.
- `dashboard/index.html` and `dashboard/data.json` are local runtime artifacts and are ignored.
- If `gh` or `openclaw` is unavailable, the dashboard reports degraded sections instead of failing the whole page.
