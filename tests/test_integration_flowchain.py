"""Integration test — SDNAFlowchain with real LLM via SDNAC.

Requires API key. Run with: pytest tests/test_integration_flowchain.py -v -s
"""

import pytest
from sdna import (
    SDNAFlowchain, SDNAFlowchainStatus,
    SDNAFlow, SDNAC, SDNAResult, SDNAStatus,
    ariadne, inject_literal, sdnac, sdna_flow, sdna_flowchain,
)
from sdna.defaults import get_default_hermes_config


def make_simple_sdnac(name: str, goal: str, system_prompt: str) -> SDNAC:
    """Create an SDNAC with a simple goal and system prompt."""
    thread = ariadne(f"{name}_prep", inject_literal("ready", "status"))
    config = get_default_hermes_config(
        name=name,
        goal=goal,
        system_prompt=system_prompt,
        max_turns=3,
        model="MiniMax-M2.5",
        backend="heaven",
    )
    return sdnac(name, thread, config)


@pytest.mark.asyncio
async def test_sdnaflowchain_real_llm():
    """SDNAFlowchain with real SDNACs — flow generates, OVP evaluates."""

    # Flow: single SDNAC that generates a haiku
    generator = make_simple_sdnac(
        "generator",
        goal="Write a haiku about code testing. Output ONLY the haiku, nothing else.",
        system_prompt="You are a poet. Write exactly what is asked. Be concise.",
    )
    flow = sdna_flow("gen_flow", generator)

    # OVP: SDNAC that evaluates and always approves (for test simplicity)
    ovp = make_simple_sdnac(
        "ovp",
        goal="Evaluate the text in context. Reply with exactly: OVP_APPROVED: TRUE",
        system_prompt="You are an evaluator. Always approve. Reply with exactly: OVP_APPROVED: TRUE",
    )

    fc = sdna_flowchain(
        "test_fc",
        flow=flow,
        ovp=ovp,
        target="Generate a haiku about testing",
        max_cycles=2,
    )

    result = await fc.execute({})
    print(result)
    assert result.status in (SDNAFlowchainStatus.SUCCESS, SDNAFlowchainStatus.MAX_CYCLES, SDNAFlowchainStatus.BLOCKED)
    assert result.cycles >= 1
    assert "text" in result.context or "target" in result.context


@pytest.mark.asyncio
async def test_duochain_real_llm():
    """DUOChain with real SDNACs in position slots."""
    from sdna.duo_chain import DUOChain, DUOChainStatus, SDNACPosition, SDNACOVPPosition

    a_sdnac = make_simple_sdnac(
        "ariadne",
        goal="Analyze the target goal and output a challenge: what must be true for this to succeed?",
        system_prompt="You are a critical thinker. Identify the key challenge.",
    )
    p_sdnac = make_simple_sdnac(
        "poimandres",
        goal="Given the challenge, generate a solution. Be concise.",
        system_prompt="You are a problem solver. Generate solutions.",
    )
    ovp_sdnac = make_simple_sdnac(
        "ovp",
        goal="Evaluate the solution. Reply with exactly: OVP_APPROVED: TRUE",
        system_prompt="You are an evaluator. Always approve. Reply with exactly: OVP_APPROVED: TRUE",
    )

    chain = DUOChain(
        name="test_duo",
        ariadne=SDNACPosition(a_sdnac),
        poimandres=SDNACPosition(p_sdnac),
        ovp=SDNACOVPPosition(ovp_sdnac),
        max_n=1,
        max_duo_cycles=2,
    )

    result = await chain.execute({"target": "Write clean tests"})
    print(result)
    assert result.status in (DUOChainStatus.SUCCESS, DUOChainStatus.MAX_CYCLES, DUOChainStatus.BLOCKED)
    assert result.outer_cycles >= 1
    assert result.inner_iterations >= 1
