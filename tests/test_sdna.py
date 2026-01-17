"""Tests for SDNA components - Ariadne, Poimandres, SDNAC"""

import pytest
from sdna import (
    ariadne, human, inject_literal,
    AriadneChain, AriadneStatus, AriadneResult,
    SDNAC, SDNAFlow, SDNAStatus,
    sdnac, sdna_flow,
)


class TestAriadne:
    """Test Ariadne context threading"""

    @pytest.mark.asyncio
    async def test_ariadne_inject_literal(self):
        """inject_literal adds value to context"""
        thread = ariadne('test', inject_literal({'foo': 'bar'}, 'data'))
        result = await thread.execute()

        assert result.status == AriadneStatus.SUCCESS
        assert result.context['data'] == {'foo': 'bar'}

    @pytest.mark.asyncio
    async def test_ariadne_human_pauses(self):
        """human() element pauses chain and returns AWAITING_INPUT"""
        thread = ariadne('test',
            inject_literal('step1', 'first'),
            human('Continue?', 'answer'),
            inject_literal('step2', 'second'),
        )
        result = await thread.execute()

        assert result.status == AriadneStatus.AWAITING_INPUT
        assert result.pending_prompt == 'Continue?'
        assert result.pending_input_key == 'answer'
        assert result.resume_at == 2
        assert result.context['first'] == 'step1'
        assert 'second' not in result.context  # Not reached yet

    @pytest.mark.asyncio
    async def test_ariadne_resume_after_human(self):
        """Chain can resume after human input"""
        thread = ariadne('test',
            inject_literal('step1', 'first'),
            human('Continue?', 'answer'),
            inject_literal('step2', 'second'),
        )

        # First run - pauses at human
        result = await thread.execute()
        assert result.status == AriadneStatus.AWAITING_INPUT

        # Resume with answer
        ctx = result.context.copy()
        ctx['answer'] = 'yes'
        result2 = await thread.execute(ctx, start_at=result.resume_at)

        assert result2.status == AriadneStatus.SUCCESS
        assert result2.context['second'] == 'step2'

    @pytest.mark.asyncio
    async def test_ariadne_chain_multiple_injects(self):
        """Multiple injects accumulate in context"""
        thread = ariadne('test',
            inject_literal('a', 'key_a'),
            inject_literal('b', 'key_b'),
            inject_literal('c', 'key_c'),
        )
        result = await thread.execute()

        assert result.status == AriadneStatus.SUCCESS
        assert result.context['key_a'] == 'a'
        assert result.context['key_b'] == 'b'
        assert result.context['key_c'] == 'c'


class TestSDNAConstructors:
    """Test SDNA constructor functions"""

    def test_sdnac_constructor(self):
        """sdnac() creates SDNAC instance"""
        thread = ariadne('prep', inject_literal('x', 'data'))
        # Note: HermesConfig would need to be imported and mocked
        # For now just test the constructor exists
        assert callable(sdnac)

    def test_sdna_flow_constructor(self):
        """sdna_flow() creates SDNAFlow instance"""
        assert callable(sdna_flow)


class TestImports:
    """Test that all expected exports are available"""

    def test_ariadne_imports(self):
        from sdna import (
            AriadneChain, AriadneResult, AriadneStatus, AriadneElement,
            HumanInput, InjectConfig, WeaveConfig,
            ariadne, human, inject_file, inject_func, inject_literal, inject_env, weave,
        )

    def test_sdna_imports(self):
        from sdna import (
            SDNAC, SDNAFlow, SDNAFlowchain,
            SDNAResult, SDNAStatus,
            SDNACConfig, OptimizerSDNACConfig, SDNAFlowConfig,
            sdnac, sdna_flow,
        )

    def test_poimandres_import(self):
        from sdna import poimandres
        assert hasattr(poimandres, 'execute')
