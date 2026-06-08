"""
ChainTool — Execute any chain ontology object (Link, Chain, EvalChain, Compiler).

This is the universal executor. The chain ontology IS the type system.
Agents learn to compose chains via skills, this tool just runs them.

Lives in sdna because it depends on chain_ontology types.
"""

import json
import traceback
from typing import Dict, Any, Optional, Union

from .chain_ontology import Link, Chain, EvalChain, Compiler, LinkResult, LinkStatus


async def execute_chain(
    chain: Link,
    context: Optional[Dict[str, Any]] = None,
    describe_only: bool = False,
) -> Dict[str, Any]:
    """Execute any chain ontology object.

    Args:
        chain: Any Link/Chain/EvalChain/Compiler instance
        context: Input context dict
        describe_only: If True, just return the chain description without executing

    Returns:
        Dict with status, context, and optional error/description
    """
    if describe_only:
        return {
            "status": "described",
            "description": chain.describe(),
            "type": type(chain).__name__,
        }

    try:
        result: LinkResult = await chain.execute(context or {})

        return {
            "status": result.status.value,
            "context": result.context,
            "error": result.error,
            "resume_path": result.resume_path,
        }
    except (TypeError, AttributeError, ValueError) as e:
        return {
            "status": "construction_error",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "hint": "Read the chain-tool skill to learn how to compose chains correctly.",
        }
    except Exception as e:
        return {
            "status": "runtime_error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


# ── Heaven Tool wrapper (optional — for agents that use BaseHeavenTool) ──

def make_chain_tool_func(chain: Link):
    """Create a closured tool function bound to a specific chain.
    
    For use with BaseHeavenTool's Closured Tool Pattern.
    The chain is captured in closure — the tool just runs it.
    """

    async def chain_tool_func(
        context_json: str = "{}",
        describe_only: bool = False,
    ) -> str:
        """Execute the bound chain with the given context."""
        try:
            context = json.loads(context_json)
        except json.JSONDecodeError as e:
            return json.dumps({"status": "error", "error": f"Invalid JSON context: {e}"})

        result = await execute_chain(chain, context, describe_only)
        return json.dumps(result, indent=2, default=str)

    return chain_tool_func
