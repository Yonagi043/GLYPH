"""Command-line entry point for the local GLYPH joint-analysis workbench."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import uvicorn

from .app import create_app
from .service import WorkbenchService


ROOT = Path(__file__).resolve().parents[3]
TEMP_ROOT = Path(tempfile.gettempdir())
DEFAULT_CATALOG = TEMP_ROOT / "glyph-workbench.sqlite3"
DEFAULT_SOCIAL = TEMP_ROOT / "glyph-social-v17.sqlite3"
DEFAULT_EXPORT_ROOT = TEMP_ROOT / "glyph-workbench-exports"
DEFAULT_BACKUP_ROOT = TEMP_ROOT / "glyph-workbench-backups"
DEFAULT_RESTORE_ROOT = TEMP_ROOT / "glyph-workbench-restores"


def _databases(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--catalog-database", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--social-database", type=Path, default=DEFAULT_SOCIAL)


def _service(args: argparse.Namespace) -> WorkbenchService:
    return WorkbenchService(
        ROOT,
        catalog_database=args.catalog_database.resolve(),
        social_database=args.social_database.resolve(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="启动本机中文统一工作台")
    _databases(serve)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8025)
    serve.add_argument("--export-root", type=Path, default=DEFAULT_EXPORT_ROOT)
    serve.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    serve.add_argument("--restore-root", type=Path, default=DEFAULT_RESTORE_ROOT)

    for name, help_text in (
        ("status", "输出模块、就绪度和数据库健康"),
        ("initialize", "验证 handoff 并登记 reference graph"),
        ("run-fixture", "运行冻结的 synthetic 联合分析"),
    ):
        command = commands.add_parser(name, help=help_text)
        _databases(command)

    system = commands.add_parser("run-system-fixture", help="运行完整 synthetic E2E")
    _databases(system)
    system.add_argument("--export-root", type=Path, default=DEFAULT_EXPORT_ROOT)
    system.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)

    export = commands.add_parser("export-demo", help="生成 no-overwrite demo 审计包")
    _databases(export)
    export.add_argument("analysis_run_id")
    export.add_argument("--export-root", type=Path, default=DEFAULT_EXPORT_ROOT)

    backup = commands.add_parser("backup", help="生成 catalog/social 协调备份")
    _databases(backup)
    backup.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)

    restore = commands.add_parser("restore-drill", help="恢复协调备份到全新临时路径")
    _databases(restore)
    restore.add_argument("backup_id")
    restore.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    restore.add_argument("--restore-root", type=Path, default=DEFAULT_RESTORE_ROOT)
    return parser


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        if args.host not in {"127.0.0.1", "localhost", "::1"}:
            print("EXTERNAL_BIND_REQUIRES_SEPARATE_APPROVAL", file=sys.stderr)
            return 2
        if not 1 <= args.port <= 65535:
            print("PORT_OUT_OF_RANGE", file=sys.stderr)
            return 2
        app = create_app(
            ROOT,
            catalog_database=args.catalog_database.resolve(),
            social_database=args.social_database.resolve(),
            export_root=args.export_root.resolve(),
            backup_root=args.backup_root.resolve(),
            restore_root=args.restore_root.resolve(),
        )
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return 0
    try:
        service = _service(args)
        if args.command == "status":
            _print(service.overview())
        elif args.command == "initialize":
            result = service.initialize_catalog()
            _print(
                {
                    "status": "initialized",
                    "handoff_count": len(result["handoffs"]),
                    "module_count": len(result["modules"]),
                    "graph": result["graph"],
                }
            )
        elif args.command == "run-fixture":
            run = service.run_fixture_analysis()
            _print(
                {
                    "distribution_label": "SYNTHETIC / DEMO",
                    "analysis_run_id": run["analysis_run_id"],
                    "status": run["status"],
                    "snapshot_sha256": run["snapshot_sha256"],
                }
            )
        elif args.command == "run-system-fixture":
            _print(
                service.run_system_fixture(
                    export_root=args.export_root.resolve(),
                    backup_root=args.backup_root.resolve(),
                )
            )
        elif args.command == "export-demo":
            _print(
                service.export_demo(
                    args.analysis_run_id, args.export_root.resolve() / "audit"
                )
            )
        elif args.command == "backup":
            _print(service.create_backup(args.backup_root.resolve()))
        elif args.command == "restore-drill":
            directory = args.restore_root.resolve() / args.backup_id / uuid.uuid4().hex[:12]
            result = service.restore_backup_drill(
                args.backup_root.resolve(),
                args.backup_id,
                target_catalog_database=directory / "catalog.sqlite3",
                target_social_database=directory / "social.sqlite3",
            )
            _print(
                {
                    "backup_id": result["backup_id"],
                    "restore_mode": result["restore_mode"],
                    "catalog_integrity": result["health"]["catalog_integrity"],
                    "social_integrity": result["health"]["social"]["integrity_check"],
                }
            )
        else:
            return 2
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())