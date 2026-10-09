#!/usr/bin/env python3
"""
CLI interface for selfbot system.

Usage:
    python -m selfbot.cli create etsy-checker /path/to/script.py --interval 3600
    python -m selfbot.cli run etsy-checker
    python -m selfbot.cli list
    python -m selfbot.cli history etsy-checker
    python -m selfbot.cli daemon  # Run scheduler
"""

import argparse
import sys
import logging

from .factory import create_system
from .domain.models import Schedule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


def cmd_create(args, system):
    """Create a new selfbot."""
    schedule = Schedule(
        cron_expr=args.cron,
        interval_seconds=args.interval,
        run_once=args.once
    )

    bot = system.manager.create(
        name=args.name,
        script_path=args.script,
        schedule=schedule,
        input_file=args.input,
        output_file=args.output,
        timeout_seconds=args.timeout,
    )
    print(f"Created: {bot}")


def cmd_run(args, system):
    """Run a selfbot immediately."""
    bot = system.manager.get_by_name(args.name)
    if not bot:
        print(f"Selfbot '{args.name}' not found")
        sys.exit(1)

    print(f"Running {bot.name}...")
    execution = system.runner.run(bot)
    print(f"Result: {execution}")

    if execution.output:
        print(f"\nOutput:\n{execution.output}")
    if execution.error:
        print(f"\nError:\n{execution.error}")
    if execution.screenshot_path:
        print(f"\nScreenshot: {execution.screenshot_path}")


def cmd_list(args, system):
    """List all selfbots."""
    bots = system.manager.list_all()
    if not bots:
        print("No selfbots configured")
        return

    for bot in bots:
        status = "enabled" if bot.enabled else "disabled"
        print(f"  [{bot.id}] {bot.name} ({status})")
        print(f"       Script: {bot.script_path}")
        if bot.schedule.cron_expr:
            print(f"       Schedule: {bot.schedule.cron_expr}")
        elif bot.schedule.interval_seconds:
            print(f"       Schedule: every {bot.schedule.interval_seconds}s")
        print()


def cmd_history(args, system):
    """Show execution history."""
    if args.name:
        bot = system.manager.get_by_name(args.name)
        if not bot:
            print(f"Selfbot '{args.name}' not found")
            sys.exit(1)
        executions = system.manager.get_history(bot.id, limit=args.limit)
    else:
        executions = system.manager.get_all_history(limit=args.limit)

    if not executions:
        print("No execution history")
        return

    for ex in executions:
        dur = f" ({ex.duration_seconds:.1f}s)" if ex.duration_seconds else ""
        print(f"  [{ex.id}] {ex.selfbot_name}: {ex.status.value}{dur}")
        print(f"       Started: {ex.started_at}")
        if ex.error:
            print(f"       Error: {ex.error[:100]}")
        print()


def cmd_delete(args, system):
    """Delete a selfbot."""
    bot = system.manager.get_by_name(args.name)
    if not bot:
        print(f"Selfbot '{args.name}' not found")
        sys.exit(1)

    system.manager.delete(bot.id)
    print(f"Deleted: {args.name}")


def cmd_daemon(args, system):
    """Run the scheduler daemon."""
    print("Loading selfbots...")
    system.load_and_schedule_all()
    print(f"Loaded {len(system.scheduler._jobs)} scheduled selfbots")
    print("Starting scheduler (Ctrl+C to stop)...")
    system.scheduler.run_blocking()


def main():
    parser = argparse.ArgumentParser(description="Selfbot management CLI")
    parser.add_argument("--storage", default="/tmp/selfbots", help="Storage directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = subparsers.add_parser("create", help="Create a selfbot")
    p_create.add_argument("name", help="Selfbot name")
    p_create.add_argument("script", help="Path to Python script")
    p_create.add_argument("--cron", help="Cron expression")
    p_create.add_argument("--interval", type=int, help="Interval in seconds")
    p_create.add_argument("--once", action="store_true", help="Run once only")
    p_create.add_argument("--input", help="Input file path")
    p_create.add_argument("--output", help="Output file path")
    p_create.add_argument("--timeout", type=int, default=300, help="Timeout seconds")

    # run
    p_run = subparsers.add_parser("run", help="Run a selfbot immediately")
    p_run.add_argument("name", help="Selfbot name")

    # list
    subparsers.add_parser("list", help="List all selfbots")

    # history
    p_history = subparsers.add_parser("history", help="Show execution history")
    p_history.add_argument("name", nargs="?", help="Selfbot name (optional)")
    p_history.add_argument("--limit", type=int, default=10, help="Max entries")

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a selfbot")
    p_delete.add_argument("name", help="Selfbot name")

    # daemon
    subparsers.add_parser("daemon", help="Run scheduler daemon")

    args = parser.parse_args()
    system = create_system(args.storage)

    commands = {
        "create": cmd_create,
        "run": cmd_run,
        "list": cmd_list,
        "history": cmd_history,
        "delete": cmd_delete,
        "daemon": cmd_daemon,
    }

    commands[args.command](args, system)


if __name__ == "__main__":
    main()
