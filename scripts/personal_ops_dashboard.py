#!/usr/bin/env python3
"""Generate a local personal operations dashboard for OpenClaw."""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "ops-dashboard.json"


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str


def run_command(args: list[str], *, cwd: Path | None = None, timeout: int = 20) -> CommandResult:
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(False, "", str(exc))
    return CommandResult(result.returncode == 0, result.stdout.strip(), result.stderr.strip())


def run_json(args: list[str], *, timeout: int = 20) -> tuple[Any | None, str | None]:
    result = run_command(args, timeout=timeout)
    if not result.ok:
        return None, result.stderr or result.stdout or "command failed"
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Config not found: {path}")
    return json.loads(path.read_text())


def age_label(epoch_ms: int | float | None, now_ms: float) -> str:
    if not epoch_ms:
        return "unknown"
    seconds = max(0, int((now_ms - float(epoch_ms)) / 1000))
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def collect_openclaw() -> dict[str, Any]:
    status, status_error = run_json(["openclaw", "status", "--json"], timeout=30)
    tasks, tasks_error = run_json(["openclaw", "tasks", "list", "--json"], timeout=30)
    audit, audit_error = run_json(["openclaw", "tasks", "audit", "--json"], timeout=30)
    sessions, sessions_error = run_json(["openclaw", "sessions", "--json", "--limit", "12"], timeout=30)
    cron = run_command(["openclaw", "cron", "list"], timeout=30)
    approvals = run_command(["openclaw", "approvals", "get"], timeout=30)
    gateway = run_command(["openclaw", "gateway", "status"], timeout=30)
    node = run_command(["openclaw", "node", "status"], timeout=30)
    return {
        "status": status,
        "status_error": status_error,
        "tasks": tasks,
        "tasks_error": tasks_error,
        "audit": audit,
        "audit_error": audit_error,
        "sessions": sessions,
        "sessions_error": sessions_error,
        "cron_text": cron.stdout,
        "cron_error": None if cron.ok else cron.stderr or cron.stdout,
        "approvals_text": approvals.stdout,
        "approvals_error": None if approvals.ok else approvals.stderr or approvals.stdout,
        "gateway_text": gateway.stdout,
        "gateway_error": None if gateway.ok else gateway.stderr or gateway.stdout,
        "node_text": node.stdout,
        "node_error": None if node.ok else node.stderr or node.stdout,
    }


def repo_name(path: Path) -> str:
    result = run_command(["git", "remote", "get-url", "origin"], cwd=path, timeout=5)
    if result.ok and result.stdout:
        return result.stdout.removesuffix(".git").split(":")[-1].split("/")[-1]
    return path.name


def collect_local_repos(paths: list[str]) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    for raw in paths:
        path = Path(raw).expanduser()
        item: dict[str, Any] = {
            "name": path.name,
            "path": str(path),
            "exists": path.exists(),
            "dirty": None,
            "branch": None,
            "last_commit": None,
            "status_lines": [],
        }
        if not path.exists():
            item["error"] = "missing"
            repos.append(item)
            continue
        if not (path / ".git").exists():
            item["error"] = "not a git repo"
            repos.append(item)
            continue
        item["name"] = repo_name(path)
        branch = run_command(["git", "branch", "--show-current"], cwd=path, timeout=5)
        status = run_command(["git", "status", "--short"], cwd=path, timeout=5)
        commit = run_command(["git", "log", "-1", "--format=%h %s"], cwd=path, timeout=5)
        item["branch"] = branch.stdout if branch.ok else "unknown"
        item["status_lines"] = status.stdout.splitlines() if status.stdout else []
        item["dirty"] = bool(item["status_lines"])
        item["last_commit"] = commit.stdout if commit.ok else "unknown"
        repos.append(item)
    return repos


def collect_github_runs(repos: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for repo in repos:
        data, error = run_json(
            [
                "gh",
                "run",
                "list",
                "--repo",
                repo,
                "--limit",
                "5",
                "--json",
                "databaseId,workflowName,status,conclusion,headBranch,headSha,createdAt,url",
            ],
            timeout=20,
        )
        if error:
            rows.append({"repo": repo, "error": error, "runs": []})
            continue
        rows.append({"repo": repo, "runs": data or []})
    return rows


def collect_memory(files: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in files:
        path = Path(raw).expanduser()
        item = {"path": str(path), "name": path.name, "exists": path.exists()}
        if path.exists():
            stat = path.stat()
            item["size"] = stat.st_size
            item["modified"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            text = path.read_text(errors="ignore")
            item["lines"] = len(text.splitlines())
            item["last_items"] = [line for line in text.splitlines()[-8:] if line.strip()]
        rows.append(item)
    return rows


def collect(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "title": config.get("title", "Personal Ops"),
        "owner": config.get("owner", "unknown"),
        "openclaw": collect_openclaw(),
        "local_repos": collect_local_repos(config.get("local_repos", [])),
        "github_runs": collect_github_runs(config.get("github_repos", [])),
        "memory": collect_memory(config.get("memory_files", [])),
    }


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def badge(label: str, tone: str = "neutral") -> str:
    return f'<span class="badge {tone}">{esc(label)}</span>'


def render_status_cards(data: dict[str, Any]) -> str:
    status = data["openclaw"].get("status") or {}
    tasks = status.get("tasks", {})
    sessions = status.get("sessions", {})
    heartbeat = status.get("heartbeat", {})
    active = tasks.get("active", "?")
    failures = tasks.get("failures", "?")
    session_count = sessions.get("count", "?")
    heartbeat_agents = heartbeat.get("agents", [])
    heartbeat_label = ", ".join(f"{a.get('agentId')} {a.get('every')}" for a in heartbeat_agents) or "unknown"
    node_ok = "running" if "Runtime: running" in data["openclaw"].get("node_text", "") else "check"
    gateway_ok = "running" if "Runtime: running" in data["openclaw"].get("gateway_text", "") else "check"
    return f"""
    <section class="summary-grid">
      <article><span>Gateway</span><strong>{esc(gateway_ok)}</strong><p>LaunchAgent service</p></article>
      <article><span>Node</span><strong>{esc(node_ok)}</strong><p>Headless node host</p></article>
      <article><span>Tasks</span><strong>{esc(active)} active</strong><p>{esc(failures)} failures tracked</p></article>
      <article><span>Sessions</span><strong>{esc(session_count)}</strong><p>{esc(heartbeat_label)}</p></article>
    </section>
    """


def render_repos(repos: list[dict[str, Any]]) -> str:
    rows = []
    for repo in repos:
        if not repo.get("exists"):
            state = badge("missing", "danger")
        elif repo.get("error"):
            state = badge(repo["error"], "warn")
        elif repo.get("dirty"):
            state = badge(f"dirty {len(repo.get('status_lines', []))}", "warn")
        else:
            state = badge("clean", "ok")
        rows.append(
            f"<tr><td>{esc(repo.get('name'))}</td><td>{state}</td><td>{esc(repo.get('branch'))}</td>"
            f"<td>{esc(repo.get('last_commit'))}</td><td><code>{esc(repo.get('path'))}</code></td></tr>"
        )
    return "<table><thead><tr><th>Repo</th><th>State</th><th>Branch</th><th>Last commit</th><th>Path</th></tr></thead><tbody>" + "\n".join(rows) + "</tbody></table>"


def render_runs(groups: list[dict[str, Any]]) -> str:
    cards = []
    for group in groups:
        if group.get("error"):
            cards.append(f"<article class='panel compact'><h3>{esc(group['repo'])}</h3>{badge('error', 'danger')}<p>{esc(group['error'])}</p></article>")
            continue
        runs = group.get("runs", [])[:3]
        lis = []
        for run in runs:
            conclusion = run.get("conclusion") or run.get("status")
            tone = "ok" if conclusion == "success" else "warn" if conclusion in {"in_progress", "queued"} else "danger"
            lis.append(
                f"<li>{badge(conclusion, tone)} <a href='{esc(run.get('url'))}'>{esc(run.get('workflowName'))}</a>"
                f"<small>{esc(run.get('headBranch'))} {esc(str(run.get('headSha', ''))[:7])}</small></li>"
            )
        cards.append(f"<article class='panel compact'><h3>{esc(group['repo'])}</h3><ul class='runs'>{''.join(lis)}</ul></article>")
    return "<div class='card-grid'>" + "\n".join(cards) + "</div>"


def render_sessions(openclaw: dict[str, Any]) -> str:
    sessions = (openclaw.get("sessions") or {}).get("sessions") or (openclaw.get("status") or {}).get("sessions", {}).get("recent", [])
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    rows = []
    for session in sessions[:10]:
        rows.append(
            f"<tr><td>{esc(session.get('kind'))}</td><td>{esc(session.get('model'))}</td>"
            f"<td>{esc(age_label(session.get('updatedAt'), now_ms))}</td>"
            f"<td>{esc(session.get('percentUsed', ''))}%</td><td><code>{esc(session.get('key'))}</code></td></tr>"
        )
    return "<table><thead><tr><th>Kind</th><th>Model</th><th>Age</th><th>Context</th><th>Session</th></tr></thead><tbody>" + "\n".join(rows) + "</tbody></table>"


def render_memory(memory: list[dict[str, Any]]) -> str:
    cards = []
    for item in memory:
        if not item.get("exists"):
            cards.append(f"<article class='panel compact'><h3>{esc(item['name'])}</h3>{badge('missing', 'warn')}</article>")
            continue
        lines = "".join(f"<li>{esc(line)}</li>" for line in item.get("last_items", [])[-5:])
        cards.append(
            f"<article class='panel compact'><h3>{esc(item['name'])}</h3>"
            f"<p>{esc(item.get('lines'))} lines · {esc(item.get('size'))} bytes</p><ul>{lines}</ul></article>"
        )
    return "<div class='card-grid'>" + "\n".join(cards) + "</div>"


def render_pre(title: str, text: str, error: str | None = None) -> str:
    tone = badge("error", "danger") if error else ""
    content = error or text or "No output."
    return f"<article class='panel'><h2>{esc(title)} {tone}</h2><pre>{esc(content)}</pre></article>"


def render_html(data: dict[str, Any]) -> str:
    title = data.get("title", "Jason Ops")
    generated = data.get("generated_at")
    audit = data["openclaw"].get("audit") or {}
    audit_summary = audit.get("summary", {})
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(title)}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#090d14; --panel:#111827; --muted:#94a3b8; --text:#e5edf7; --line:#253244; --accent:#2dd4bf; --ok:#34d399; --warn:#fbbf24; --danger:#fb7185; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.5 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ max-width:1180px; margin:0 auto; padding:28px 18px 56px; }}
    header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-end; margin-bottom:22px; }}
    h1 {{ margin:0; font-size:34px; letter-spacing:0; }}
    h2 {{ margin:0 0 14px; font-size:18px; }}
    h3 {{ margin:0 0 10px; font-size:15px; }}
    a {{ color:var(--accent); text-decoration:none; }}
    code, pre {{ font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    pre {{ max-height:360px; overflow:auto; padding:14px; border-radius:8px; background:#060a10; border:1px solid var(--line); white-space:pre-wrap; }}
    table {{ width:100%; border-collapse:collapse; overflow:hidden; border-radius:8px; }}
    th, td {{ padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
    section {{ margin:18px 0; }}
    .hero {{ border:1px solid var(--line); background:linear-gradient(135deg, rgba(45,212,191,.16), rgba(17,24,39,.78)); border-radius:12px; padding:22px; }}
    .summary-grid, .card-grid {{ display:grid; gap:12px; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); }}
    .summary-grid article, .panel {{ border:1px solid var(--line); background:var(--panel); border-radius:10px; padding:16px; }}
    .summary-grid span, small {{ color:var(--muted); }}
    .summary-grid strong {{ display:block; margin:5px 0; font-size:24px; }}
    .panel.compact {{ padding:14px; }}
    .badge {{ display:inline-flex; align-items:center; border:1px solid var(--line); border-radius:999px; padding:2px 8px; font-size:12px; color:var(--muted); }}
    .badge.ok {{ color:var(--ok); border-color:rgba(52,211,153,.35); }}
    .badge.warn {{ color:var(--warn); border-color:rgba(251,191,36,.35); }}
    .badge.danger {{ color:var(--danger); border-color:rgba(251,113,133,.35); }}
    .runs, .panel ul {{ padding-left:18px; margin:8px 0 0; }}
    .runs li {{ margin-bottom:8px; }}
    @media (max-width: 700px) {{ header {{ display:block; }} h1 {{ font-size:28px; }} table {{ font-size:12px; }} }}
  </style>
</head>
<body>
  <main>
    <header class="hero">
      <div>
        <h1>{esc(title)}</h1>
        <p>Local operating view for Jason, OpenClaw, repos, tasks, memory, and deploys.</p>
      </div>
      <div>{badge("generated " + str(generated), "ok")}</div>
    </header>
    {render_status_cards(data)}
    <section class="panel"><h2>TaskFlow / Task Audit</h2><p>{badge(str(audit_summary.get("combined", {}).get("errors", 0)) + " errors", "ok" if audit_summary.get("combined", {}).get("errors", 0) == 0 else "danger")} {badge(str(audit_summary.get("combined", {}).get("warnings", 0)) + " warnings", "ok" if audit_summary.get("combined", {}).get("warnings", 0) == 0 else "warn")}</p></section>
    <section class="panel"><h2>Local Repos</h2>{render_repos(data.get("local_repos", []))}</section>
    <section><h2>GitHub Runs</h2>{render_runs(data.get("github_runs", []))}</section>
    <section class="panel"><h2>Recent Sessions</h2>{render_sessions(data.get("openclaw", {}))}</section>
    <section><h2>Memory</h2>{render_memory(data.get("memory", []))}</section>
    {render_pre("Cron", data["openclaw"].get("cron_text", ""), data["openclaw"].get("cron_error"))}
    {render_pre("Approvals", data["openclaw"].get("approvals_text", ""), data["openclaw"].get("approvals_error"))}
  </main>
</body>
</html>
"""


def command_generate(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config).expanduser())
    data = collect(config)
    out = Path(args.output).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (out / "index.html").write_text(render_html(data))
    print(f"Wrote {out / 'index.html'}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--config", default=str(DEFAULT_CONFIG))
    generate.add_argument("--output", default=str(ROOT / "dashboard"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "generate":
        return command_generate(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
