"""Command-line entry point for the local social-narrative system."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import uvicorn

from .web import create_app
from .service import SocialNarrativeService


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE = ROOT / "data" / "raw" / "social" / "glyph-social.sqlite3"
DEFAULT_EXPORT_ROOT = ROOT / "data" / "processed" / "social_narrative_v0" / "exports"
DEFAULT_BACKUP_ROOT = ROOT / "data" / "raw" / "social" / "backups"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    serve = subcommands.add_parser("serve", help="启动本机中文研究系统")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    serve.add_argument("--export-root", type=Path, default=DEFAULT_EXPORT_ROOT)
    serve.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    serve.add_argument(
        "--proxy",
        default=os.environ.get("GLYPH_OUTBOUND_PROXY"),
        help="外网 HTTP/SOCKS 代理；也可设置 GLYPH_OUTBOUND_PROXY",
    )
    backup = subcommands.add_parser("backup", help="创建并校验 SQLite 一致性备份")
    backup.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    backup.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    restore = subcommands.add_parser("restore", help="恢复备份并自动保存恢复前数据库")
    restore.add_argument("backup_id")
    restore.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    restore.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    restore.add_argument(
        "--confirm",
        required=True,
        help="必须与 backup_id 完全相同；恢复前应停止 Web 服务",
    )
    export = subcommands.add_parser("export-run", help="导出并验证一个已结束的运行")
    export.add_argument("collection_run_id")
    export.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    export.add_argument("--output-root", type=Path, default=DEFAULT_EXPORT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        app = create_app(
            args.database.resolve(),
            outbound_proxy=args.proxy,
            export_root=args.export_root.resolve(),
            backup_root=args.backup_root.resolve(),
        )
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return 0
    service = SocialNarrativeService(args.database.resolve())
    if args.command == "backup":
        print(json.dumps(
            service.create_backup(args.backup_root.resolve()),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    if args.command == "restore":
        if args.confirm != args.backup_id:
            print("--confirm 必须与 backup_id 完全相同")
            return 2
        print(json.dumps(
            service.restore_backup(args.backup_root.resolve(), args.backup_id),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    if args.command == "export-run":
        print(json.dumps(
            service.export_run(args.collection_run_id, args.output_root.resolve()),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())