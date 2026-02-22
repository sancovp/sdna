"""
SDNAC flow composition for Crystal Ball story-machine workflows.

Pattern mirrors hierarchical_summarize:
- create_flow(...) builds SDNAC units
- run(...) executes the SDNAFlow
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .ariadne import ariadne, inject_func, inject_literal
from .config import HeavenAgentArgs, HeavenHermesArgs, HeavenInputs, HermesConfig
from .sdna import SDNAFlow, sdnac, sdna_flow

logger = logging.getLogger(__name__)

HEAVEN_SYSTEM_PROMPT = (
    "You are a Crystal Ball graph-operations agent. "
    "Execute tools immediately. Keep outputs concise, concrete, and auditable."
)

HEAVEN_INPUTS = HeavenInputs(
    agent=HeavenAgentArgs(
        provider="ANTHROPIC",
        max_tokens=8000,
        use_uni_api=False,
    ),
    hermes=HeavenHermesArgs(),
)

MAP_REVIEW_GOAL = """
You are reviewing a Cypher->CrystalBall projection that has already been executed.

Inputs in context:
- cb_map_result: tool output from mapping
- cb_map_stats: parsed stats from mapped JSON

Return:
1) One-line health verdict
2) Top 5 structural risks
3) Exact next operation to run
"""

ENRICH_REVIEW_GOAL = """
You are reviewing an enriched Crystal Ball artifact that has already been generated.

Inputs in context:
- cb_enrich_result
- cb_enriched_stats

Return:
1) One-line quality verdict
2) What is now represented well
3) What is still underfilled (character/archetype/psychodynamics)
4) A ranked top-5 backlog
"""

AUTOBAKE_OPERATOR_GOAL = """
Drive iterative improvement with these constraints:
- Prefer dedup + canonicalization first
- Use bounded collapse, not full superposition expansion
- Track both agent and user score trends over time

Inputs in context:
- cb_map_stats
- cb_enriched_stats
- input_cypher, mapped_cb_json, enriched_cb_json

Return:
1) Proposed next autobake cycle (exact 1-3 actions)
2) Stop condition for this cycle
3) Score target for agent and user
"""


def _flow_config(
    *,
    name: str,
    goal: str,
    model: str,
    backend: str,
    max_turns: int,
    heaven_inputs: HeavenInputs,
    additional_mcp_servers: Optional[Dict[str, Any]] = None,
) -> HermesConfig:
    """
    Build HermesConfig for Crystal Ball flow.

    Defaults to no MCP dependencies (mcp_servers={}).
    If additional_mcp_servers is provided explicitly, include only those.
    """
    mcp_servers = dict(additional_mcp_servers or {})
    return HermesConfig(
        name=name,
        goal=goal,
        system_prompt=HEAVEN_SYSTEM_PROMPT,
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
        backend=backend,
        heaven_inputs=heaven_inputs,
        mcp_servers=mcp_servers,
    )


def create_flow(
    input_cypher: str,
    mapped_cb_json: str,
    enriched_cb_json: str,
    space_name: str = "StoryMachineProjection",
    model: str = "MiniMax-M2.5-highspeed",
    backend: str = "heaven",
    additional_mcp_servers: Optional[Dict[str, Any]] = None,
) -> SDNAFlow:
    """Build the Crystal Ball SDNAFlow (map -> enrich -> operator)."""
    logger.info("Creating crystal_ball flow")

    input_cypher = str(Path(input_cypher).expanduser().resolve())
    mapped_cb_json = str(Path(mapped_cb_json).expanduser().resolve())
    enriched_cb_json = str(Path(enriched_cb_json).expanduser().resolve())

    mapper = sdnac(
        "cb_mapper",
        ariadne(
            "cb_mapper_prep",
            inject_literal(input_cypher, "input_cypher"),
            inject_literal(mapped_cb_json, "mapped_cb_json"),
            inject_literal(space_name, "space_name"),
            inject_func(
                "sdna.crystal_ball",
                "cb_map_cypher_to_cb",
                "cb_map_result",
                input_cypher="$input_cypher",
                output_cb_json="$mapped_cb_json",
                space_name="$space_name",
            ),
            inject_func(
                "sdna.crystal_ball",
                "cb_read_cb_stats",
                "cb_map_stats",
                cb_json_path="$mapped_cb_json",
            ),
        ),
        config=_flow_config(
            name="cb_mapper",
            goal=MAP_REVIEW_GOAL,
            model=model,
            max_turns=6,
            backend=backend,
            heaven_inputs=HEAVEN_INPUTS,
            additional_mcp_servers=additional_mcp_servers,
        ),
    )

    enricher = sdnac(
        "cb_enricher",
        ariadne(
            "cb_enricher_prep",
            inject_literal(mapped_cb_json, "mapped_cb_json"),
            inject_literal(enriched_cb_json, "enriched_cb_json"),
            inject_func(
                "sdna.crystal_ball",
                "cb_enrich_story_machine_cb",
                "cb_enrich_result",
                input_cb_json="$mapped_cb_json",
                output_cb_json="$enriched_cb_json",
            ),
            inject_func(
                "sdna.crystal_ball",
                "cb_read_cb_stats",
                "cb_enriched_stats",
                cb_json_path="$enriched_cb_json",
            ),
        ),
        config=_flow_config(
            name="cb_enricher",
            goal=ENRICH_REVIEW_GOAL,
            model=model,
            max_turns=8,
            backend=backend,
            heaven_inputs=HEAVEN_INPUTS,
            additional_mcp_servers=additional_mcp_servers,
        ),
    )

    operator = sdnac(
        "cb_autobake_operator",
        ariadne(
            "cb_operator_prep",
            inject_literal(input_cypher, "input_cypher"),
            inject_literal(mapped_cb_json, "mapped_cb_json"),
            inject_literal(enriched_cb_json, "enriched_cb_json"),
            inject_func(
                "sdna.crystal_ball",
                "cb_read_cb_stats",
                "cb_map_stats",
                cb_json_path="$mapped_cb_json",
            ),
            inject_func(
                "sdna.crystal_ball",
                "cb_read_cb_stats",
                "cb_enriched_stats",
                cb_json_path="$enriched_cb_json",
            ),
        ),
        config=_flow_config(
            name="cb_autobake_operator",
            goal=AUTOBAKE_OPERATOR_GOAL,
            model=model,
            max_turns=10,
            backend=backend,
            heaven_inputs=HEAVEN_INPUTS,
            additional_mcp_servers=additional_mcp_servers,
        ),
    )

    flow = sdna_flow(
        "crystal_ball_story_machine",
        mapper,
        enricher,
        operator,
    )

    logger.info("Flow created with 3 SDNACs")
    return flow


async def run(
    input_cypher: str,
    mapped_cb_json: str,
    enriched_cb_json: str,
    space_name: str = "StoryMachineProjection",
    model: str = "MiniMax-M2.5-highspeed",
    backend: str = "heaven",
    additional_mcp_servers: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
):
    """Execute the Crystal Ball flow."""
    flow = create_flow(
        input_cypher=input_cypher,
        mapped_cb_json=mapped_cb_json,
        enriched_cb_json=enriched_cb_json,
        space_name=space_name,
        model=model,
        backend=backend,
        additional_mcp_servers=additional_mcp_servers,
    )
    ctx = dict(context) if context else {}
    return await flow.execute(ctx)
