#!/usr/bin/env python3
"""CLI wrapper for queue system - handles package imports correctly."""

import sys
import logging

# Add parent to path for package imports
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sdna.selfbot_extensions.infrastructure.task_queue import TaskQueue, ConversationMode
from sdna.selfbot_extensions.infrastructure.queue_processor import QueueProcessor, start_claude_if_needed
from sdna.selfbot_extensions.domain.automation import AutomationRegistry, Automation

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def main():
    if len(sys.argv) < 2:
        print("Claude Queue System")
        print()
        print("Queue commands:")
        print("  queue add 'prompt' [--priority N] [--mode new|resume|continue] [--cron '0 9 * * *']")
        print("  queue list")
        print("  queue next")
        print("  queue remove TASK_ID")
        print()
        print("Processor commands:")
        print("  process run       # Run daemon (blocking)")
        print("  process once      # Process one task and exit")
        print("  process status    # Show processor status")
        print("  process boot      # Start Claude if not running")
        print()
        print("Automation commands:")
        print("  auto list         # List loaded automations")
        print("  auto fire NAME    # Fire an automation now")
        print("  auto show NAME    # Show automation details")
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    # Queue commands
    if cmd == "queue":
        queue = TaskQueue()
        if not args:
            print("Usage: queue [add|list|next|remove]")
            sys.exit(1)

        subcmd = args[0]

        if subcmd == "add" and len(args) >= 2:
            prompt = args[1]
            priority = 5
            mode = ConversationMode.CONTINUE
            cron_expr = None

            i = 2
            while i < len(args):
                if args[i] == "--priority" and i + 1 < len(args):
                    priority = int(args[i + 1])
                    i += 2
                elif args[i] == "--mode" and i + 1 < len(args):
                    mode = ConversationMode(args[i + 1])
                    i += 2
                elif args[i] == "--cron" and i + 1 < len(args):
                    cron_expr = args[i + 1]
                    i += 2
                else:
                    i += 1

            task = queue.add(prompt, mode=mode, priority=priority, cron_expression=cron_expr)
            if cron_expr:
                print(f"Added recurring task {task.id} (cron: {cron_expr})")
            else:
                print(f"Added task {task.id}")

        elif subcmd == "list":
            pending = queue.list_pending()
            running = queue.list_running()

            if running:
                print("RUNNING:")
                for t in running:
                    print(f"  [{t.id}] (started {t.started_at})")
                    print(f"    {t.prompt[:60]}...")

            if pending:
                print("PENDING:")
                for t in sorted(pending, key=lambda x: -x.priority):
                    sched = f" @{t.scheduled_at}" if t.scheduled_at else ""
                    cron = f" [cron: {t.cron_expression}]" if t.cron_expression else ""
                    print(f"  [{t.id}] priority={t.priority}{sched}{cron}")
                    print(f"    {t.prompt[:60]}...")

            if not pending and not running:
                print("Queue is empty")

        elif subcmd == "next":
            task = queue.get_next()
            if task:
                print(f"Next: [{task.id}] priority={task.priority}")
                print(f"  {task.prompt}")
            else:
                print("No tasks ready")

        elif subcmd == "remove" and len(args) >= 2:
            if queue.remove_task(args[1]):
                print(f"Removed {args[1]}")
            else:
                print(f"Not found: {args[1]}")

        else:
            print(f"Unknown queue command: {subcmd}")

    # Processor commands
    elif cmd == "process":
        if not args:
            print("Usage: process [run|once|status|boot]")
            sys.exit(1)

        subcmd = args[0]

        if subcmd == "run":
            if not start_claude_if_needed():
                print("ERROR: Could not start Claude")
                sys.exit(1)

            processor = QueueProcessor()
            print(f"Starting queue processor (session: {processor.session})")
            print("Press Ctrl+C to stop")
            processor.run()

        elif subcmd == "once":
            if not start_claude_if_needed():
                print("ERROR: Could not start Claude")
                sys.exit(1)

            processor = QueueProcessor()
            if processor.process_one():
                print("Processed one task")
            else:
                print("No tasks in queue")

        elif subcmd == "status":
            processor = QueueProcessor()
            status = processor.status()
            print(f"Session: {status['session'] or 'not connected'}")
            print(f"Pending: {status['pending_tasks']}")
            print(f"Running: {status['running_tasks']}")
            if status['current_task']:
                print(f"Current: {status['current_task']}")

        elif subcmd == "boot":
            if start_claude_if_needed():
                print("Claude is running")
            else:
                print("Failed to start Claude")
                sys.exit(1)

        else:
            print(f"Unknown process command: {subcmd}")

    # Automation commands
    elif cmd == "auto":
        registry = AutomationRegistry()
        registry.load_all()

        if not args:
            print("Usage: auto [list|fire|show]")
            sys.exit(1)

        subcmd = args[0]

        if subcmd == "list":
            autos = registry.list_all()
            if autos:
                print("Automations:")
                for name in autos:
                    auto = registry.get(name)
                    sched = f" [{auto.schedule}]" if auto.schedule else ""
                    print(f"  {name}{sched}")
                    if auto.schema.description:
                        print(f"    {auto.schema.description[:60]}")
            else:
                print("No automations loaded")

        elif subcmd == "fire" and len(args) >= 2:
            name = args[1]
            auto = registry.get(name)
            if not auto:
                print(f"Automation not found: {name}")
                sys.exit(1)

            queue = TaskQueue()
            result = auto.fire(queue)
            print(f"Fired: {name}")
            if result.get("queued_task_id"):
                print(f"  Queued task: {result['queued_task_id']}")
            if result.get("code_result"):
                print(f"  Code result: {result['code_result']}")

        elif subcmd == "show" and len(args) >= 2:
            name = args[1]
            auto = registry.get(name)
            if not auto:
                print(f"Automation not found: {name}")
                sys.exit(1)

            print(f"Name: {auto.name}")
            print(f"Description: {auto.schema.description}")
            print(f"Schedule: {auto.schedule or 'manual'}")
            print(f"Session: {auto.get_session_mode()} (id={auto.session_id or 'main'})")
            print(f"Priority: {auto.schema.priority}")
            print(f"Tags: {auto.schema.tags}")
            if auto.schema.code_pointer:
                print(f"Code: {auto.schema.code_pointer}")
            if auto.schema.prompt_template:
                print(f"Prompt:\n{auto.render_prompt()[:300]}...")

        else:
            print(f"Unknown auto command: {subcmd}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
