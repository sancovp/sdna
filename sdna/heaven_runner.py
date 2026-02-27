"""
Heaven runner backend for SDNA — bridges into Heaven's hermes_step.

ADAPTOR: Converts SDNA HermesConfig → Heaven HermesConfig + HeavenAgentConfig.
Heaven handles all key resolution, agent creation, execution internally.

Two Heaven objects are built:
1. HeavenAgentConfig — WHO does it (system_prompt, model, provider, tools, mcp_servers)
2. Heaven HermesConfig — WHAT to do (goal, iterations, agent reference)

Fields are sourced from:
- SDNA HermesConfig (name, system_prompt, model, mcp_servers, goal, max_turns)
- HeavenInputs.agent (provider, temperature, max_tokens, thinking_budget, heaven_tools, extra_model_kwargs)
- HeavenInputs.hermes (history_id, return_summary, ai_messages_only, continuation, etc.)
"""

import logging
from typing import Optional, Dict, Any, Union

from .config import HermesConfig, HeavenInputs, HeavenAgentArgs, HeavenHermesArgs
from .runner import StepResult, StepStatus
from .tools import parse_blocked_from_text, BlockedReport

logger = logging.getLogger(__name__)

HEAVEN_AVAILABLE = False
try:
    from heaven_base.tool_utils.hermes_utils import hermes_step
    from heaven_base.configs.hermes_config import HermesConfig as HeavenHermesConfig
    from heaven_base.baseheavenagent import HeavenAgentConfig, ProviderEnum
    HEAVEN_AVAILABLE = True
except ImportError:
    logger.debug("heaven-framework not installed — heaven_runner unavailable")


MINIMAX_BASE_URL = "https://api.minimax.io/anthropic"
MINIMAX_DEFAULT_MODEL = "MiniMax-M2.5-highspeed"


def _translate_mcp_servers(mcp_servers: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Translate SDNA MCP server configs to Heaven format.

    SDNA (Claude Code SDK) format: {command, args, env}
    Heaven (langchain-mcp-adapters) format: {command, args, env, transport}

    Adds "transport": "stdio" to any server config that has "command" but no "transport".
    Configs with "url" (SSE/streamable_http) must already have "transport" set.
    """
    translated = {}
    for name, server_config in mcp_servers.items():
        cfg = dict(server_config)
        # Claude Code uses "type", langchain_mcp_adapters uses "transport"
        if "type" in cfg and "transport" not in cfg:
            cfg["transport"] = cfg.pop("type")
        elif "command" in cfg and "transport" not in cfg:
            cfg["transport"] = "stdio"
        translated[name] = cfg
    return translated


def _build_heaven_agent_config(config: HermesConfig) -> "HeavenAgentConfig":
    """
    Build a HeavenAgentConfig from SDNA HermesConfig + HeavenInputs.agent.

    Pulls shared fields from SDNA HermesConfig (name, system_prompt, model, mcp_servers).
    Pulls Heaven-specific fields from heaven_inputs.agent (provider, temperature, etc.).

    When extra_model_kwargs is None, sets MiniMax defaults:
    - anthropic_api_url pointing to MiniMax
    Heaven handles all key resolution internally.
    """
    agent_args = config.heaven_inputs.agent if config.heaven_inputs else HeavenAgentArgs()

    # Resolve provider enum from string
    provider = ProviderEnum[agent_args.provider]

    # Default model to MiniMax-M2.5 when not specified
    model = config.model or MINIMAX_DEFAULT_MODEL

    # Default extra_model_kwargs to MiniMax URL when not explicitly set
    # Heaven resolves API keys internally — do NOT set keys here
    extra_model_kwargs = agent_args.extra_model_kwargs
    if extra_model_kwargs is None:
        extra_model_kwargs = {
            "anthropic_api_url": MINIMAX_BASE_URL,
        }

    # Convert mcp_servers dict to "mcp__server__all" tool strings (PATH2)
    # PATH2 uses Heaven's MCP registry (heaven_mcp_config.json) via _get_mcp_server_config
    # This is more reliable than passing mcp_servers dict directly (PATH1)
    tools = list(agent_args.tools)
    if config.mcp_servers:
        for server_name in config.mcp_servers:
            tool_str = f"mcp__{server_name}__all"
            if tool_str not in tools:
                tools.append(tool_str)

    return HeavenAgentConfig(
        name=config.name or "sdna_agent",
        system_prompt=config.system_prompt or "",
        model=model,
        provider=provider,
        temperature=agent_args.temperature,
        max_tokens=agent_args.max_tokens,
        thinking_budget=agent_args.thinking_budget,
        tools=tools,
        mcp_servers=None,  # PATH2 handles MCPs via registry — no dict needed
        extra_model_kwargs=extra_model_kwargs,
        use_uni_api=agent_args.use_uni_api,
        additional_kws=agent_args.additional_kws,
        additional_kw_instructions=agent_args.additional_kw_instructions,
    )


def _build_heaven_hermes_config(
    config: HermesConfig,
    goal: str,
    agent: Any,
) -> "HeavenHermesConfig":
    """
    Build a Heaven HermesConfig from SDNA HermesConfig + HeavenInputs.hermes.

    Goal comes from config.resolve_goal(). Iterations from config.max_turns.
    Agent is the built HeavenAgentConfig (or pre-built heaven_agent passthrough).
    Extra hermes args from heaven_inputs.hermes.
    """
    hermes_args = config.heaven_inputs.hermes if config.heaven_inputs else HeavenHermesArgs()

    heaven_config = HeavenHermesConfig()
    heaven_config.args_template = {
        "goal": goal,
        "iterations": config.max_turns or 1,
        "agent": agent,
        "history_id": hermes_args.history_id,
        "return_summary": hermes_args.return_summary,
        "ai_messages_only": hermes_args.ai_messages_only,
        "continuation": hermes_args.continuation,
        "additional_tools": hermes_args.additional_tools,
        "remove_agents_config_tools": hermes_args.remove_agents_config_tools,
        "orchestration_preprocess": hermes_args.orchestration_preprocess,
        "variable_inputs": hermes_args.variable_inputs,
        "system_prompt_suffix": hermes_args.system_prompt_suffix,
    }
    return heaven_config


async def heaven_agent_step(
    config: Union[HermesConfig, Dict[str, Any]],
    variable_inputs: Optional[Dict[str, Any]] = None,
    agent_constructor_kwargs: Optional[Dict[str, Any]] = None,
) -> StepResult:
    """
    Execute a single agent step via Heaven's hermes_step.

    Drop-in replacement for agent_step() from runner.py.
    Builds HeavenAgentConfig + Heaven HermesConfig from SDNA HermesConfig.
    """
    if not HEAVEN_AVAILABLE:
        return StepResult(
            status=StepStatus.ERROR,
            error="heaven-framework not installed (pip install heaven-framework)"
        )

    if isinstance(config, dict):
        config = HermesConfig(**config)

    merged_inputs = dict(variable_inputs) if variable_inputs else {}

    if config.brain_query and config.brain_project_root:
        try:
            from .brain import get_project_context
            context = await get_project_context(
                config.brain_project_root,
                config.brain_query
            )
            merged_inputs[config.inject_context_as] = context
        except Exception as e:
            merged_inputs[config.inject_context_as] = f"[Brain query failed: {e}]"

    prompt = config.resolve_goal(merged_inputs)

    # Wire history_id from context (previous SDNAC output) into config for continuation.
    # When an SDNAC executes, its output includes history_id which lands in ctx.
    # The next SDNAC in a flow/chain receives that ctx as variable_inputs.
    # If config doesn't already have a history_id set, use the one from context.
    # This enables conversation continuation across SDNACs in flows and DUOChain cycles.
    ctx_history_id = merged_inputs.get("history_id")
    if ctx_history_id:
        if config.heaven_inputs is None:
            config.heaven_inputs = HeavenInputs()
        if not config.heaven_inputs.hermes.history_id:
            config.heaven_inputs.hermes.history_id = ctx_history_id

    # Resolve agent: use pre-built heaven_agent if provided, otherwise build from inputs
    if config.heaven_agent is not None:
        agent = config.heaven_agent
    else:
        agent = _build_heaven_agent_config(config)

    # Build Heaven HermesConfig with resolved agent
    heaven_hermes = _build_heaven_hermes_config(config, prompt, agent)

    # Build constructor kwargs — use_uni_api MUST be passed here because
    # BaseHeavenAgent.__init__ defaults use_uni_api=True and reads it from
    # constructor param, NOT from config.use_uni_api
    agent_args = config.heaven_inputs.agent if config.heaven_inputs else HeavenAgentArgs()
    constructor_kwargs = dict(agent_constructor_kwargs or {})
    constructor_kwargs.setdefault("use_uni_api", agent_args.use_uni_api)

    try:
        result = await hermes_step(
            target_container="",
            source_container="",
            hermes_config=heaven_hermes,
            agent_constructor_kwargs=constructor_kwargs,
        )

        # hermes_step returns str on error, dict on success
        if isinstance(result, str):
            return StepResult(
                status=StepStatus.ERROR,
                error=result,
            )

        final_text = result.get("prepared_message", "")
        agent_status = result.get("agent_status") or {}
        extracted_content = agent_status.get("extracted_content") if isinstance(agent_status, dict) else None
        extracted_keys = list(extracted_content.keys()) if isinstance(extracted_content, dict) else []
        output_payload = {
            "text": final_text,
            "prepared_message": final_text,
            "history_id": result.get("history_id"),
            "agent_name": result.get("agent_name"),
            "agent_status": agent_status,
            "extracted_content": extracted_content or {},
            "extracted_content_keys": extracted_keys,
            "raw_result": result,
        }

        # Check Heaven's block report first (WriteBlockReportTool path)
        if result.get("has_block_report"):
            text = final_text
            # Try SDNA XML parse first, fall back to constructing from Heaven's text
            blocked_report = parse_blocked_from_text(text)
            if not blocked_report:
                blocked_report = BlockedReport(
                    goal=prompt,
                    obstacle="Agent filed a block report via WriteBlockReportTool",
                    reason=text,
                    raw_text=text,
                )
            blocked_report.save(config.name)
            return StepResult(
                status=StepStatus.BLOCKED,
                blocked=blocked_report,
                output=output_payload,
            )

        # Fallback: check SDNA-style block report in text
        if final_text:
            blocked_report = parse_blocked_from_text(final_text)
            if blocked_report:
                blocked_report.save(config.name)
                return StepResult(
                    status=StepStatus.BLOCKED,
                    blocked=blocked_report,
                    output=output_payload,
                )

        return StepResult(
            status=StepStatus.SUCCESS,
            output=output_payload,
        )

    except Exception as e:
        logger.error("heaven_agent_step failed: %s", e, exc_info=True)
        return StepResult(
            status=StepStatus.ERROR,
            error=str(e),
        )
