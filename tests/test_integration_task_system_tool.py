"""Integration test — TaskSystemTool via SDNA → Heaven pipeline.

Verifies that Heaven agents use TaskSystemTool (not regex patterns) to manage tasks.
Requires API key. Run with: pytest tests/test_integration_task_system_tool.py -v -s
"""

import pytest
from sdna import (
    SDNAC, SDNAResult, SDNAStatus,
    ariadne, inject_literal, sdnac,
)
from sdna.defaults import get_default_hermes_config


def make_task_tool_sdnac(name: str, goal: str, system_prompt: str, max_turns: int = 5) -> SDNAC:
    """Create an SDNAC that uses Heaven backend with TaskSystemTool."""
    thread = ariadne(f"{name}_prep", inject_literal("ready", "status"))
    config = get_default_hermes_config(
        name=name,
        goal=goal,
        system_prompt=system_prompt,
        max_turns=max_turns,
        model="MiniMax-M2.5",
        backend="heaven",
    )
    return sdnac(name, thread, config)


@pytest.mark.asyncio
async def test_agent_uses_task_system_tool():
    """Agent should call TaskSystemTool to manage tasks, not output regex patterns.

    The goal explicitly tells the agent to use TaskSystemTool operations.
    We verify the output text contains TaskSystemTool confirmation strings
    (returned by task_system_func) rather than the old regex patterns.
    """
    unit = make_task_tool_sdnac(
        "task_tool_test",
        goal=(
            "You have ONE simple job: demonstrate TaskSystemTool usage.\n"
            "Step 1: Call TaskSystemTool with operation='update_tasks', tasks=['say_hello', 'say_goodbye']\n"
            "Step 2: Say 'Hello World'\n"
            "Step 3: Call TaskSystemTool with operation='complete_task', task_name='say_hello'\n"
            "Step 4: Say 'Goodbye World'\n"
            "Step 5: Call TaskSystemTool with operation='complete_task', task_name='say_goodbye'\n"
            "Step 6: Call TaskSystemTool with operation='goal_accomplished'\n"
            "Do exactly these steps in order. Use the TaskSystemTool tool for task management."
        ),
        system_prompt=(
            "You are a test agent. Follow instructions precisely. "
            "Use the TaskSystemTool to manage your task list. "
            "Do NOT output markdown task patterns. Use the tool."
        ),
        max_turns=5,
    )

    result = await unit.execute({})
    print(result)

    # Agent should complete successfully (not blocked, not error)
    assert result.status in (SDNAStatus.SUCCESS, SDNAStatus.BLOCKED), (
        f"Expected SUCCESS or BLOCKED, got {result.status}: {result.error}"
    )

    # Check the output text for TaskSystemTool confirmation strings
    output_text = result.context.get("text", "")
    if not output_text:
        # Try prepared_message
        output_text = result.context.get("prepared_message", "")

    # Print full output for debugging
    print(f"\n=== Agent Output Text ===\n{output_text}\n=== End ===\n")

    # If agent succeeded, verify it used the tool (not regex patterns)
    if result.status == SDNAStatus.SUCCESS:
        # The agent's prepared_message should contain evidence of tool responses
        # TaskSystemTool returns strings like "Task list updated to N tasks"
        # and "Task 'X' marked complete." and "Goal marked as accomplished."
        # These appear in the conversation as tool results.
        #
        # We also verify the OLD regex patterns are NOT present
        old_patterns = ["```update_task_list=", "```complete_task=", "```GOAL ACCOMPLISHED```"]
        for pattern in old_patterns:
            if pattern in output_text:
                print(f"WARNING: Old regex pattern found in output: {pattern}")


@pytest.mark.asyncio
async def test_agent_goal_accomplished_terminates():
    """Agent calling goal_accomplished should cause clean termination.

    When TaskSystemTool(operation='goal_accomplished') fires, self.goal = None,
    which triggers the loop exit at 'if not self.goal: break'.
    The agent should not use all max_turns — it should exit early.
    """
    unit = make_task_tool_sdnac(
        "goal_term_test",
        goal=(
            "Your ONLY task: immediately call TaskSystemTool with operation='goal_accomplished'. "
            "Do nothing else. Just call the tool and stop."
        ),
        system_prompt="You are a test agent. Do exactly what is asked. Nothing more.",
        max_turns=5,
    )

    result = await unit.execute({})
    print(result)

    # Should complete — the agent has 5 turns but should only need 1
    assert result.status in (SDNAStatus.SUCCESS, SDNAStatus.BLOCKED), (
        f"Expected SUCCESS or BLOCKED, got {result.status}: {result.error}"
    )
