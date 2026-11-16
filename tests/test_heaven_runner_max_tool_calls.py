"""HeavenAgentArgs.max_tool_calls reaches the BaseHeavenAgent constructor.

max_tool_calls is a constructor argument of BaseHeavenAgent (default 10 tool calls per iteration), not a
HeavenAgentConfig field, so passing it through extra_agent_kwargs is silently dropped. heaven_agent_step
hands the field to hermes_step as agent_constructor_kwargs; unset, heaven keeps its default.
"""
import asyncio

from sdna import heaven_runner
from sdna.config import HeavenAgentArgs, HeavenInputs, HermesConfig


def _constructor_kwargs(agent_args):
    seen = {}

    async def fake_hermes_step(**kw):
        seen.update(kw["agent_constructor_kwargs"])
        return {"history_id": "h", "prepared_message": "", "agent_status": {}}

    real = heaven_runner.hermes_step
    heaven_runner.hermes_step = fake_hermes_step
    try:
        cfg = HermesConfig(name="probe", system_prompt="p", goal="g", max_turns=2, backend="heaven",
                           heaven_inputs=HeavenInputs(agent=agent_args))
        asyncio.run(heaven_runner.heaven_agent_step(cfg))
    finally:
        heaven_runner.hermes_step = real
    return seen


def test_max_tool_calls_reaches_the_agent_constructor():
    assert _constructor_kwargs(HeavenAgentArgs(max_tool_calls=2000))["max_tool_calls"] == 2000


def test_unset_max_tool_calls_leaves_heaven_default():
    assert "max_tool_calls" not in _constructor_kwargs(HeavenAgentArgs())
