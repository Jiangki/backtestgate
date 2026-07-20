"""Command-line interface for BacktestGate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .audit import audit
from .loader import InputError, load_audit_directory
from .report import infer_output_format, render, render_share_json, write_report
from .scaffold import ScaffoldError, initialise_audit_directory


EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backtestgate",
        description="Offline trust gate for TradingView Pine backtests.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    init_command = commands.add_parser(
        "init", help="create a safe starter directory for one real audit"
    )
    init_command.add_argument(
        "audit_dir",
        type=Path,
        help="new or empty directory to initialize",
    )

    audit_command = commands.add_parser(
        "audit", help="audit one conventional BacktestGate input directory"
    )
    audit_command.add_argument(
        "audit_dir",
        type=Path,
        help="directory with strategy.pine, trades.csv, performance.csv and manifest.json",
    )
    audit_command.add_argument(
        "--format",
        choices=("text", "json", "markdown", "html"),
        default="text",
        help="stdout format (default: text)",
    )
    audit_command.add_argument(
        "-o",
        "--output",
        type=Path,
        help="write report; format is inferred from .html, .json or .md",
    )
    audit_command.add_argument(
        "--share-output",
        type=Path,
        help="write a privacy-safe validation receipt as JSON",
    )
    audit_command.add_argument(
        "--fail-on",
        choices=("block", "warn"),
        default="block",
        help="CI threshold for exit 1 (default: block)",
    )
    return parser


def _init(args: argparse.Namespace) -> int:
    try:
        target = initialise_audit_directory(args.audit_dir)
    except ScaffoldError as exc:
        print("backtestgate: error: {}".format(exc), file=sys.stderr)
        return EXIT_USAGE
    print("Initialized BacktestGate audit directory: {}".format(target))
    print("Next: follow {}/README.txt and edit manifest.json.".format(target))
    return EXIT_OK


def _audit(args: argparse.Namespace) -> int:
    try:
        audit_input = load_audit_directory(args.audit_dir)
        result = audit(audit_input)
    except InputError as exc:
        print("backtestgate: error: {}".format(exc), file=sys.stderr)
        return EXIT_USAGE

    if args.output is not None and args.share_output is not None:
        if args.output.expanduser().resolve() == args.share_output.expanduser().resolve():
            print(
                "backtestgate: error: --output and --share-output must use different paths",
                file=sys.stderr,
            )
            return EXIT_USAGE

    print(render(result, args.format))
    if args.output is not None:
        output_path = args.output.expanduser()
        output_format = infer_output_format(output_path)
        try:
            write_report(output_path, render(result, output_format))
        except OSError as exc:
            print("backtestgate: error: {}".format(exc), file=sys.stderr)
            return EXIT_USAGE
        print(
            "BacktestGate wrote {} report to {}".format(
                output_format, output_path
            ),
            file=sys.stderr,
        )
    if args.share_output is not None:
        share_path = args.share_output.expanduser()
        try:
            write_report(share_path, render_share_json(result))
        except OSError as exc:
            print("backtestgate: error: {}".format(exc), file=sys.stderr)
            return EXIT_USAGE
        print(
            "BacktestGate wrote privacy-safe validation receipt to {}".format(
                share_path
            ),
            file=sys.stderr,
        )

    should_fail = result.gate == "BLOCK" or (
        args.fail_on == "warn" and result.gate == "WARN"
    )
    return EXIT_FINDINGS if should_fail else EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return _init(args)
    if args.command == "audit":
        return _audit(args)
    parser.error("a command is required")
    return EXIT_USAGE
