"""
SDNA State - The TypedDict that flows through LangGraph execution.

This is the native state format for SDNA's LangGraph substrate.
All chains and elements operate on this state.
"""

from typing import TypedDict, Dict, Any, List, Optional


class SDNAState(TypedDict, total=False):
    """
    State that flows through SDNA LangGraph execution.

    Core Fields:
        context: The accumulated context dict that Ariadne builds
        status: Current execution status
        error: Error message if status is "error"

    Human-in-the-Loop Fields:
        awaiting_input: Whether we're paused waiting for human
        pending_prompt: The prompt to show the human
        pending_input_key: Where to store the human's response
        pending_choices: Optional list of choices
        resume_at: Index to resume Ariadne chain from

    Execution Tracking:
        current_unit: For SDNAFlow - which SDNAC we're on
        total_units: Total number of units in flow
        iteration: Current iteration count
        max_iterations: Max iterations allowed

    Results:
        results: List of results from each step
        output: Final output from Poimandres
    """

    # Core
    context: Dict[str, Any]
    status: str  # "pending" | "success" | "error" | "awaiting_input" | "blocked"
    error: Optional[str]

    # Human-in-the-loop
    awaiting_input: bool
    pending_prompt: Optional[str]
    pending_input_key: Optional[str]
    pending_choices: Optional[List[str]]
    resume_at: Optional[int]

    # Execution tracking
    current_unit: int
    total_units: int
    iteration: int
    max_iterations: int

    # Results
    results: List[Dict[str, Any]]
    output: Optional[Any]


def initial_state(context: Dict[str, Any] = None) -> SDNAState:
    """Create initial SDNAState with defaults."""
    return SDNAState(
        context=context or {},
        status="pending",
        error=None,
        awaiting_input=False,
        pending_prompt=None,
        pending_input_key=None,
        pending_choices=None,
        resume_at=None,
        current_unit=0,
        total_units=1,
        iteration=0,
        max_iterations=10,
        results=[],
        output=None,
    )
