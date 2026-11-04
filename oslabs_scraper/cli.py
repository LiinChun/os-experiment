"""Command line interface: ``oslabs-scrape <command>``."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import DEFAULT_BASE_URL, Config
from .discover import parse_nav
from .fetcher import DEFAULT_USER_AGENT, Fetcher
from .errors import ScrapeError
from .mirror import Mirror, Report
from .publish import GitError, default_message, publish
from .verify import format_result, verify_mirror

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_INCOMPLETE = 3


def _configure_stdio() -> None:
    """Force UTF-8 output so Chinese titles survive the Windows console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - unusual streams
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oslabs-scrape",
        description="把 https://os-labs.p.cs-lab.top 的原始 HTML 快照镜像到 git 仓库。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  oslabs-scrape scrape              # 抓取全站到 raw/\n"
            "  oslabs-scrape scrape --prune      # 同时删除源站已删除的页面\n"
            "  oslabs-scrape verify              # 校验快照完整性\n"
            "  GITHUB_TOKEN=ghp_xxx oslabs-scrape publish\n"
            "  GITHUB_TOKEN=ghp_xxx oslabs-scrape sync   # 抓取 + 提交 + 推送\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"oslabs-scrape {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")

    scrape = subparsers.add_parser("scrape", help="抓取站点并写入快照目录")
    _add_scrape_options(scrape)
    scrape.add_argument("--prune", action="store_true", help="删除源站上已不存在的文件")
    scrape.add_argument("--dry-run", action="store_true", help="只报告将要做什么，不写文件")

    verify = subparsers.add_parser("verify", help="校验快照与 manifest 是否一致")
    _add_common_options(verify)
    verify.add_argument("--no-links", action="store_true", help="跳过页面内引用检查")
    verify.add_argument(
        "--strict-refs",
        action="store_true",
        help="页面内引用目标缺失时也返回非零（源站自身的 404 也算失败）",
    )

    publish_cmd = subparsers.add_parser("publish", help="提交并推送到 GitHub")
    publish_cmd.add_argument("--repo", default=".", help="仓库根目录（默认当前目录）")
    publish_cmd.add_argument("--remote", default="origin", help="远程名，默认 origin")
    publish_cmd.add_argument("--branch", default="", help="分支名，默认当前分支")
    publish_cmd.add_argument("--message", default="", help="提交信息")
    publish_cmd.add_argument(
        "--token-env", default="GITHUB_TOKEN", help="存放 token 的环境变量名"
    )
    publish_cmd.add_argument("--no-push", action="store_true", help="只提交，不推送")
    publish_cmd.add_argument("--dry-run", action="store_true", help="只显示将要提交的文件")

    sync = subparsers.add_parser("sync", help="抓取 + 提交 + 推送（一条命令完成日常更新）")
    _add_scrape_options(sync)
    sync.add_argument("--prune", action="store_true", help="删除源站上已不存在的文件")
    sync.add_argument("--repo", default=".", help="仓库根目录（默认当前目录）")
    sync.add_argument("--remote", default="origin", help="远程名，默认 origin")
    sync.add_argument("--branch", default="", help="分支名，默认当前分支")
    sync.add_argument("--message", default="", help="提交信息")
    sync.add_argument(
        "--token-env", default="GITHUB_TOKEN", help="存放 token 的环境变量名"
    )
    sync.add_argument("--no-push", action="store_true", help="只提交，不推送")

    listing = subparsers.add_parser("list", help="只打印站点导航，不下载")
    _add_common_options(listing)

    return parser


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="站点根地址")
    parser.add_argument("--out", default="raw", help="快照输出目录（默认 raw）")
    parser.add_argument("--delay", type=float, default=0.3, help="请求间隔秒数（默认 0.3）")
    parser.add_argument("--timeout", type=float, default=30.0, help="单请求超时秒数")
    parser.add_argument("--retries", type=int, default=3, help="失败重试次数")
    parser.add_argument("--insecure", action="store_true", help="跳过 TLS 证书校验")
    parser.add_argument(
        "--max-asset-bytes", type=int, default=8 * 1024 * 1024, help="单个响应大小上限"
    )
    parser.add_argument("--ignore-robots", action="store_true", help="忽略 robots.txt")
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="SUBSTRING",
        help="URL 中包含该子串时跳过（可重复）",
    )
    parser.add_argument("--quiet", action="store_true", help="只输出汇总")


def _add_scrape_options(parser: argparse.ArgumentParser) -> None:
    _add_common_options(parser)
    parser.add_argument("--force", action="store_true", help="忽略缓存，强制重新下载")
    parser.add_argument("--max-pages", type=int, default=500, help="最多抓取页面数")
    parser.add_argument("--include-external", action="store_true", help="同时镜像外部域资源")
    parser.add_argument(
        "--no-index", action="store_true", help="不生成 INDEX.md"
    )


def config_from_args(args: argparse.Namespace) -> Config:
    return Config(
        base_url=args.base_url,
        out_dir=Path(args.out),
        index_path=None if getattr(args, "no_index", False) else Path("INDEX.md"),
        user_agent="",
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        verify_tls=not args.insecure,
        max_bytes=args.max_asset_bytes,
        max_pages=getattr(args, "max_pages", 500),
        respect_robots=not args.ignore_robots,
        include_external=getattr(args, "include_external", False),
        skip_patterns=tuple(args.skip),
    )


def _log(message: str) -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def command_scrape(args: argparse.Namespace) -> int:
    config = config_from_args(args)
    logger = None if args.quiet else _log
    _log(f"→ 抓取 {config.base_url} 到 {config.out_dir}/")
    mirror = Mirror(config, log=logger)
    report = mirror.run(
        force=getattr(args, "force", False),
        prune=getattr(args, "prune", False),
        dry_run=getattr(args, "dry_run", False),
    )
    args._report = report  # type: ignore[attr-defined]

    _print_report(report, config, dry_run=getattr(args, "dry_run", False))
    return EXIT_OK if report.page_count else EXIT_FAILURE


def command_verify(args: argparse.Namespace) -> int:
    config = config_from_args(args)
    result = verify_mirror(config, check_links=not args.no_links)
    for line in format_result(result):
        _log(line)
    if not result.healthy:
        return EXIT_FAILURE
    # A page may reference a file that the site itself does not serve (this
    # site 404s /js/image-captions.js on every page). That is reported, but it
    # only fails the run when --strict-refs is given.
    if args.strict_refs and not result.clean:
        return EXIT_INCOMPLETE
    return EXIT_OK


def command_list(args: argparse.Namespace) -> int:
    config = config_from_args(args)
    with Fetcher(
        user_agent=config.user_agent or DEFAULT_USER_AGENT,
        timeout=config.timeout,
        retries=config.retries,
        delay=config.delay,
        verify=config.verify_tls,
        respect_robots=config.respect_robots,
    ) as fetcher:
        response = fetcher.get(config.base_url)
    items = parse_nav(response.text(), config.base_url)
    if not items:
        _log("未解析到导航（站点结构可能已变化）")
        return EXIT_FAILURE

    def emit(nodes, depth: int = 0) -> None:
        for node in nodes:
            mark = "  " * depth + ("- " if depth else "")
            target = f"  {node.href}" if node.href else ""
            _log(f"{mark}{node.title}{target}")
            emit(node.children, depth + 1)

    emit(items)
    return EXIT_OK


def command_publish(args: argparse.Namespace) -> int:
    token = os.environ.get(args.token_env, "").strip()
    if not token and not args.no_push and not args.dry_run:
        _log(f"× 环境变量 {args.token_env} 为空，无法推送。")
        _log("  请先导出带 repo 权限的 GitHub Token，或加 --no-push 只提交。")
        return EXIT_USAGE
    try:
        result = publish(
            Path(args.repo),
            message=args.message,
            remote=args.remote,
            branch=args.branch,
            token=token,
            push=not args.no_push,
            dry_run=args.dry_run,
        )
    except GitError as exc:
        _log(f"× {exc}")
        return EXIT_FAILURE

    if args.dry_run:
        _log(f"待提交文件 {len(result.changed_files)} 个")
        for name in result.changed_files[:40]:
            _log(f"  {name}")
        return EXIT_OK
    if result.committed:
        _log(f"✓ 已提交 {result.commit_sha[:8]}：{result.commit_message}")
    else:
        _log("· 工作区没有变化，无需提交")
    if result.pushed:
        _log(f"✓ 已推送到 {result.branch}")
    return EXIT_OK


def command_sync(args: argparse.Namespace) -> int:
    code = command_scrape(args)
    if code != EXIT_OK:
        _log("× 抓取未获取到任何页面，跳过提交")
        return code

    token = os.environ.get(args.token_env, "").strip()
    push = bool(token) and not args.no_push
    if not push and not args.no_push:
        _log(f"! 环境变量 {args.token_env} 为空：只做本地提交，不推送")
        _log(f"  之后可以用 {args.token_env}=... python -m oslabs_scraper publish 补推")

    message = args.message or _commit_message_from_report(getattr(args, "_report", None))
    try:
        result = publish(
            Path(args.repo),
            message=message,
            remote=args.remote,
            branch=args.branch,
            token=token,
            push=push,
        )
    except GitError as exc:
        _log(f"× {exc}")
        return EXIT_FAILURE

    if result.committed:
        _log(f"✓ 已提交 {result.commit_sha[:8]}：{result.commit_message}")
    else:
        _log("· 快照没有变化，无需提交")
    if result.pushed:
        _log(f"✓ 已推送到 {result.branch}")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _commit_message_from_report(report: Report | None) -> str:
    if report is None:
        return default_message()
    parts = []
    if report.page_new:
        parts.append(f"+{report.page_new} 页")
    if report.page_changed:
        parts.append(f"~{report.page_changed} 页")
    if report.asset_new:
        parts.append(f"+{report.asset_new} 资源")
    if report.asset_changed:
        parts.append(f"~{report.asset_changed} 资源")
    if report.removed:
        parts.append(f"-{len(report.removed)} 过期文件")
    detail = "，".join(parts) if parts else "无内容变化"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"scrape: {detail} ({stamp})"


def _print_report(report: Report, config: Config, *, dry_run: bool) -> None:
    _log("")
    _log("快照目录: " + str(config.out_dir))
    _log("页面标题: " + (report.site_title or "(未知)"))
    for line in report.summary_lines():
        _log(line)
    if report.hit_page_limit:
        _log("! 页面数量达到 --max-pages 上限，可能还有页面未抓取")
    if report.removed and dry_run:
        _log("（dry-run：未真正删除）")
    if report.errors:
        _log("")
        _log("失败的 URL:")
        for error in report.errors[:20]:
            _log(f"  - {error}")
        if len(report.errors) > 20:
            _log(f"  ... 共 {len(report.errors)} 条")


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "scrape": command_scrape,
        "verify": command_verify,
        "publish": command_publish,
        "sync": command_sync,
        "list": command_list,
    }
    handler = handlers[args.command]
    try:
        return handler(args)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        _log("\n已中断")
        return 130
    except ScrapeError as exc:
        _log(f"× {exc}")
        return EXIT_FAILURE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
