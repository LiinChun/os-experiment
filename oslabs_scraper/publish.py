"""Commit and push the mirrored files with ``git``.

The module never stores the token anywhere: it is injected into a one-shot
push URL and every captured output is scrubbed before it reaches the terminal
or an exception message.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


class GitError(RuntimeError):
    """A git command failed."""


@dataclass
class PublishResult:
    branch: str = ""
    committed: bool = False
    commit_sha: str = ""
    commit_message: str = ""
    pushed: bool = False
    changed_files: list[str] = field(default_factory=list)


def _git(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
    token: str = "",
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    if not executable:
        raise GitError("找不到 git 可执行文件，请先安装 Git 并在 PATH 中可用")
    environment = dict(os.environ)
    environment.setdefault("GIT_TERMINAL_PROMPT", "0")
    environment.setdefault("GIT_PAGER", "cat")
    try:
        completed = subprocess.run(
            [executable, *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
    except OSError as exc:  # pragma: no cover - platform guard
        raise GitError(f"无法执行 git: {exc}") from exc

    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise GitError(_scrub(f"git {' '.join(args)} 失败:\n{detail}", token))
    return completed


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def current_branch(root: Path) -> str:
    completed = _git(["rev-parse", "--abbrev-ref", "HEAD"], root, check=False)
    branch = completed.stdout.strip()
    return branch if completed.returncode == 0 and branch and branch != "HEAD" else "main"


def remote_url(root: Path, remote: str = "origin") -> str:
    completed = _git(["remote", "get-url", remote], root, check=False)
    return completed.stdout.strip()


def changed_files(root: Path) -> list[str]:
    completed = _git(["status", "--porcelain", "--untracked-files=all"], root, check=False)
    if completed.returncode != 0:
        return []
    return [line[3:] for line in completed.stdout.splitlines() if line.strip()]


def _authenticated_url(url: str, token: str) -> str:
    """Return *url* with an ``x-access-token`` credential embedded."""
    if not token:
        return url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return url
    if "@" in parts.netloc:
        host = parts.netloc.rsplit("@", 1)[1]
    else:
        host = parts.netloc
    netloc = f"x-access-token:{token}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def default_message() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"scrape: update mirror ({stamp})"


def publish(
    root: Path,
    *,
    message: str = "",
    remote: str = "origin",
    branch: str = "",
    token: str = "",
    push: bool = True,
    dry_run: bool = False,
) -> PublishResult:
    """Stage everything, commit if needed and (optionally) push to *remote*.

    Raises :class:`GitError` when git itself fails.  When the working tree is
    already clean the result simply reports ``committed=False``.
    """
    root = Path(root)
    result = PublishResult(branch=branch or current_branch(root))

    if dry_run:
        result.changed_files = changed_files(root)
        return result

    _git(["add", "-A"], root, token=token)
    staged = _git(["diff", "--cached", "--quiet"], root, check=False)
    if staged.returncode != 0:
        result.changed_files = changed_files(root)
        commit_message = message or default_message()
        _git(["commit", "-m", commit_message], root, token=token)
        result.committed = True
        result.commit_message = commit_message
        result.commit_sha = _git(["rev-parse", "HEAD"], root, check=False).stdout.strip()
    else:
        result.changed_files = changed_files(root)

    if not push:
        return result

    url = remote_url(root, remote)
    if not url:
        raise GitError(f"没有名为 {remote} 的远程仓库，请先执行 git remote add")

    target = _authenticated_url(url, token)
    try:
        _git(["push", target, f"HEAD:refs/heads/{result.branch}"], root, token=token)
    except GitError as exc:
        raise GitError(
            f"推送失败（请检查 token 是否有效、是否具有 repo 写权限）:\n{exc}"
        ) from exc
    result.pushed = True
    return result
