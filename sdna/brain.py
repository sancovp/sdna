"""
Brain Agent - Neural-inspired knowledge retrieval using Claude Agent SDK.

A lightweight implementation of the brain agent pattern that:
1. Loads "neurons" (documents/files) from a directory
2. Uses Haiku to determine which neurons are relevant to a query (CognizeTool)
3. Uses Haiku to extract instructions from relevant neurons (InstructTool)
4. Synthesizes final instructions

This version uses the Claude Agent SDK for auth and execution.
"""

import os
import json
import asyncio
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

# Use Claude Agent SDK
try:
    from claude_agent_sdk import query as sdk_query, ClaudeAgentOptions
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False


@dataclass
class BrainConfig:
    """Configuration for a brain (collection of neurons)."""
    name: str
    directory: str  # Path to neuron files
    description: str = ""
    chunk_size: int = 4000  # Max chars per neuron chunk
    extensions: List[str] = field(default_factory=lambda: [".md", ".txt", ".py", ".json", ".yaml"])


@dataclass
class Neuron:
    """A single neuron (knowledge source)."""
    path: str
    content: str
    name: str
    relevance: float = 0.0
    reasoning: str = ""
    instructions: str = ""


@dataclass
class CognitionResult:
    """Result from brain cognition."""
    query: str
    relevant_neurons: List[Neuron]
    all_neurons: List[Neuron]
    instructions: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class Brain:
    """
    Neural-inspired knowledge retrieval system.

    Uses Claude Agent SDK with Haiku for fast, cheap cognition across document collections.
    """

    def __init__(self, config: BrainConfig, model: str = "haiku"):
        self.config = config
        self.model = model  # "haiku", "sonnet", or "opus"
        self.neurons: List[Neuron] = []
        self._loaded = False

    def load_neurons(self) -> int:
        """Load all neurons from the configured directory."""
        self.neurons = []
        directory = Path(self.config.directory)

        if not directory.exists():
            raise ValueError(f"Brain directory does not exist: {directory}")

        for ext in self.config.extensions:
            for file_path in directory.rglob(f"*{ext}"):
                # Skip hidden files and __pycache__
                if file_path.name.startswith('.') or '__pycache__' in str(file_path):
                    continue

                try:
                    content = file_path.read_text(encoding='utf-8')

                    # Chunk if needed
                    if len(content) > self.config.chunk_size:
                        chunks = self._chunk_content(content, file_path)
                        self.neurons.extend(chunks)
                    else:
                        self.neurons.append(Neuron(
                            path=str(file_path),
                            content=content,
                            name=file_path.name
                        ))
                except Exception as e:
                    print(f"Warning: Could not load {file_path}: {e}")

        self._loaded = True
        return len(self.neurons)

    def _chunk_content(self, content: str, file_path: Path) -> List[Neuron]:
        """Split content into chunks."""
        chunks = []
        chunk_size = self.config.chunk_size

        for i in range(0, len(content), chunk_size):
            chunk_content = content[i:i + chunk_size]
            chunk_num = i // chunk_size + 1
            chunks.append(Neuron(
                path=f"{file_path}:chunk{chunk_num}",
                content=chunk_content,
                name=f"{file_path.name}:chunk{chunk_num}"
            ))

        return chunks

    async def cognize(self, query: str, max_relevant: int = 5) -> List[Neuron]:
        """
        Find neurons relevant to the query using Haiku.

        This is the CognizeTool equivalent - parallel processing of all neurons.
        """
        if not self._loaded:
            self.load_neurons()

        if not self.neurons:
            return []

        # Process neurons in parallel batches
        batch_size = 10
        tasks = []

        for neuron in self.neurons:
            tasks.append(self._check_relevance(neuron, query))

        # Run all relevance checks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Update neurons with results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.neurons[i].relevance = 0.0
                self.neurons[i].reasoning = f"Error: {result}"
            else:
                self.neurons[i].relevance = result[0]
                self.neurons[i].reasoning = result[1]

        # Sort by relevance and return top N
        relevant = sorted(self.neurons, key=lambda n: n.relevance, reverse=True)
        return [n for n in relevant[:max_relevant] if n.relevance > 0.5]

    async def _check_relevance(self, neuron: Neuron, query: str) -> Tuple[float, str]:
        """Check if a neuron is relevant to the query using Claude SDK."""
        if not SDK_AVAILABLE:
            return (0.0, "Claude Agent SDK not available")

        prompt = f"""You are evaluating if this document is relevant to a query.

<document name="{neuron.name}">
{neuron.content[:2000]}
</document>

<query>{query}</query>

Respond with JSON only, no other text:
{{"relevant": true, "score": 0.85, "reasoning": "brief explanation"}}"""

        try:
            # Collect response from SDK
            response_text = ""
            async for message in sdk_query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    allowed_tools=[],
                    max_turns=1,
                    model=self.model
                )
            ):
                if hasattr(message, 'content'):
                    for block in message.content:
                        if hasattr(block, 'text'):
                            response_text = block.text

            # Parse JSON from response
            content = response_text.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            data = json.loads(content.strip())
            return (data.get("score", 0.0), data.get("reasoning", ""))

        except Exception as e:
            return (0.0, str(e))

    async def instruct(self, neurons: List[Neuron], query: str) -> Dict[str, str]:
        """
        Generate instructions from relevant neurons using Haiku.

        This is the InstructTool equivalent.
        """
        if not neurons:
            return {}

        tasks = []
        for neuron in neurons:
            tasks.append(self._get_instructions(neuron, query))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        instructions = {}
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                instructions[neurons[i].name] = f"Error: {result}"
            else:
                instructions[neurons[i].name] = result
                neurons[i].instructions = result

        return instructions

    async def _get_instructions(self, neuron: Neuron, query: str) -> str:
        """Get instructions from a neuron for the query."""
        if not SDK_AVAILABLE:
            return "Claude Agent SDK not available"

        prompt = f"""Based on this document, provide instructions relevant to the query.

<document name="{neuron.name}">
{neuron.content[:3000]}
</document>

<query>{query}</query>

<relevance_reasoning>{neuron.reasoning}</relevance_reasoning>

Provide clear, actionable instructions based on the document content. Be specific and practical."""

        try:
            response_text = ""
            async for message in sdk_query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    allowed_tools=[],
                    max_turns=1,
                    model=self.model
                )
            ):
                if hasattr(message, 'content'):
                    for block in message.content:
                        if hasattr(block, 'text'):
                            response_text = block.text

            return response_text

        except Exception as e:
            return f"Error: {e}"

    async def query(self, query_text: str, max_neurons: int = 5) -> CognitionResult:
        """
        Full brain query: cognize + instruct + synthesize.

        Args:
            query_text: The question/query to process
            max_neurons: Maximum relevant neurons to use

        Returns:
            CognitionResult with all neurons and synthesized instructions
        """
        # Step 1: Cognize - find relevant neurons
        relevant = await self.cognize(query_text, max_neurons)

        if not relevant:
            return CognitionResult(
                query=query_text,
                relevant_neurons=[],
                all_neurons=self.neurons,
                instructions="No relevant knowledge found for this query."
            )

        # Step 2: Instruct - get instructions from relevant neurons
        await self.instruct(relevant, query_text)

        # Step 3: Synthesize - combine instructions
        instructions = self._synthesize_instructions(relevant, query_text)

        return CognitionResult(
            query=query_text,
            relevant_neurons=relevant,
            all_neurons=self.neurons,
            instructions=instructions
        )

    def _synthesize_instructions(self, neurons: List[Neuron], query: str) -> str:
        """Combine instructions from multiple neurons."""
        if not neurons:
            return "No instructions available."

        parts = []
        for neuron in neurons:
            if neuron.instructions:
                parts.append(f"## From {neuron.name}\n\n{neuron.instructions}")

        return "\n\n---\n\n".join(parts)


# Brain registry for managing multiple brains
_brain_registry: Dict[str, Brain] = {}


def register_brain(name: str, directory: str, **kwargs) -> Brain:
    """Register a brain in the global registry."""
    config = BrainConfig(name=name, directory=directory, **kwargs)
    brain = Brain(config)
    _brain_registry[name] = brain
    return brain


def get_brain(name: str) -> Optional[Brain]:
    """Get a brain from the registry."""
    return _brain_registry.get(name)


def list_brains() -> List[str]:
    """List all registered brains."""
    return list(_brain_registry.keys())


@dataclass
class HierarchicalBrainConfig:
    """Configuration for a hierarchical brain system."""
    name: str
    sub_brains: List[BrainConfig]  # Sub-brains to query
    synthesis_model: str = "sonnet"  # Use stronger model for synthesis
    cognition_model: str = "haiku"  # Use fast model for cognition
    max_neurons_per_brain: int = 3
    max_parallel: int = 5  # Max concurrent brain queries


@dataclass
class HierarchicalResult:
    """Result from hierarchical brain query."""
    query: str
    sub_results: Dict[str, CognitionResult]  # brain_name -> result
    synthesis: str  # Final synthesized answer
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class HierarchicalBrain:
    """
    A brain that queries multiple sub-brains and synthesizes results.

    Use this for:
    - Large codebases split into modules
    - Multi-domain knowledge bases
    - Scaling beyond single-brain neuron limits

    Pattern:
    1. Query all sub-brains in parallel (cognize + instruct)
    2. Collect their instructions
    3. Synthesize into unified response
    """

    def __init__(self, config: HierarchicalBrainConfig):
        self.config = config
        self.sub_brains: Dict[str, Brain] = {}
        self._loaded = False

    def load(self) -> Dict[str, int]:
        """Load all sub-brains. Returns neuron counts per brain."""
        counts = {}
        for brain_config in self.config.sub_brains:
            brain = Brain(brain_config, model=self.config.cognition_model)
            count = brain.load_neurons()
            self.sub_brains[brain_config.name] = brain
            counts[brain_config.name] = count
        self._loaded = True
        return counts

    async def query(self, query_text: str) -> HierarchicalResult:
        """
        Query all sub-brains and synthesize results.

        1. Parallel cognize across all sub-brains
        2. Parallel instruct on relevant neurons
        3. Synthesize all instructions into final answer
        """
        if not self._loaded:
            self.load()

        # Step 1: Query all sub-brains in parallel
        tasks = []
        brain_names = []
        for name, brain in self.sub_brains.items():
            tasks.append(brain.query(query_text, max_neurons=self.config.max_neurons_per_brain))
            brain_names.append(name)

        # Run with concurrency limit
        sub_results = {}
        for i in range(0, len(tasks), self.config.max_parallel):
            batch = tasks[i:i + self.config.max_parallel]
            batch_names = brain_names[i:i + self.config.max_parallel]
            results = await asyncio.gather(*batch, return_exceptions=True)

            for name, result in zip(batch_names, results):
                if isinstance(result, Exception):
                    sub_results[name] = CognitionResult(
                        query=query_text,
                        relevant_neurons=[],
                        all_neurons=[],
                        instructions=f"Error querying brain: {result}"
                    )
                else:
                    sub_results[name] = result

        # Step 2: Synthesize all results
        synthesis = await self._synthesize(query_text, sub_results)

        return HierarchicalResult(
            query=query_text,
            sub_results=sub_results,
            synthesis=synthesis
        )

    async def _synthesize(self, query: str, sub_results: Dict[str, CognitionResult]) -> str:
        """Synthesize instructions from all sub-brains into unified response."""
        if not SDK_AVAILABLE:
            return "Claude Agent SDK not available"

        # Build context from all sub-brain results
        context_parts = []
        for brain_name, result in sub_results.items():
            if result.relevant_neurons:
                context_parts.append(f"## From {brain_name}\n\n{result.instructions}")

        if not context_parts:
            return "No relevant information found across any knowledge domains."

        combined_context = "\n\n---\n\n".join(context_parts)

        prompt = f"""You are synthesizing knowledge from multiple specialized domains to answer a query.

<query>{query}</query>

<domain_knowledge>
{combined_context}
</domain_knowledge>

Synthesize this information into a coherent, actionable response.
- Identify common themes across domains
- Resolve any contradictions
- Provide a unified answer that draws on all relevant sources
- Be specific and practical"""

        try:
            response_text = ""
            async for message in sdk_query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    allowed_tools=[],
                    max_turns=1,
                    model=self.config.synthesis_model
                )
            ):
                if hasattr(message, 'content'):
                    for block in message.content:
                        if hasattr(block, 'text'):
                            response_text = block.text

            return response_text

        except Exception as e:
            return f"Synthesis error: {e}"


class ProjectBrain:
    """
    Convenience class for querying an entire project/codebase.

    Automatically creates sub-brains for different directory patterns:
    - src/ or lib/ -> "source" brain
    - tests/ -> "tests" brain
    - docs/ -> "docs" brain
    - etc.

    Or you can define custom module mappings.
    """

    DEFAULT_MODULES = {
        "source": ["src", "lib", "app", "pkg"],
        "tests": ["tests", "test", "spec"],
        "docs": ["docs", "documentation", "doc"],
        "config": ["config", "settings", "."],  # root level configs
    }

    def __init__(
        self,
        project_root: str,
        name: str = "project",
        modules: Optional[Dict[str, List[str]]] = None,
        extensions: Optional[List[str]] = None
    ):
        self.project_root = Path(project_root)
        self.name = name
        self.modules = modules or self.DEFAULT_MODULES
        self.extensions = extensions or [".py", ".ts", ".js", ".md", ".yaml", ".json"]
        self.hierarchical_brain: Optional[HierarchicalBrain] = None

    def discover_and_load(self) -> Dict[str, int]:
        """
        Discover project structure and create sub-brains.

        Returns neuron counts per discovered module.
        """
        sub_brain_configs = []

        for module_name, dir_patterns in self.modules.items():
            for pattern in dir_patterns:
                module_path = self.project_root / pattern
                if module_path.is_dir():
                    sub_brain_configs.append(BrainConfig(
                        name=f"{self.name}_{module_name}",
                        directory=str(module_path),
                        description=f"{module_name} module of {self.name}",
                        extensions=self.extensions
                    ))
                    break  # Use first matching pattern

        if not sub_brain_configs:
            # Fallback: treat entire project as one brain
            sub_brain_configs.append(BrainConfig(
                name=f"{self.name}_all",
                directory=str(self.project_root),
                description=f"All files in {self.name}",
                extensions=self.extensions
            ))

        # Create hierarchical brain
        self.hierarchical_brain = HierarchicalBrain(HierarchicalBrainConfig(
            name=self.name,
            sub_brains=sub_brain_configs,
        ))

        return self.hierarchical_brain.load()

    async def query(self, query_text: str) -> HierarchicalResult:
        """Query the project brain."""
        if not self.hierarchical_brain:
            self.discover_and_load()
        return await self.hierarchical_brain.query(query_text)

    async def get_context(self, task_description: str) -> str:
        """
        Get relevant project context for a task.

        This is the main entry point for chain steps that need context.
        Returns synthesized instructions from relevant parts of the codebase.
        """
        result = await self.query(task_description)
        return result.synthesis


# Convenience function for chains
async def get_project_context(
    project_root: str,
    task_description: str,
    modules: Optional[Dict[str, List[str]]] = None
) -> str:
    """
    Get relevant project context for a task.

    Use this in chain steps to gather context before doing work.

    Args:
        project_root: Path to project root
        task_description: What you're trying to do
        modules: Optional custom module mappings

    Returns:
        Synthesized context/instructions from relevant project files
    """
    brain = ProjectBrain(project_root, modules=modules)
    brain.discover_and_load()
    result = await brain.query(task_description)
    return result.synthesis


# Example usage
async def example():
    """Example of using the brain system."""
    # Simple brain
    brain = register_brain(
        name="hermes_knowledge",
        directory="./hermes",
        description="Knowledge about the Hermes workflow system",
        extensions=[".py", ".md"]
    )
    count = brain.load_neurons()
    print(f"Loaded {count} neurons")

    result = await brain.query("How do I create a chain of configs?")
    print(f"\nQuery: {result.query}")
    print(f"Relevant neurons: {len(result.relevant_neurons)}")
    print(f"\nInstructions:\n{result.instructions[:500]}...")

    # Hierarchical brain
    print("\n\n--- Hierarchical Brain ---")
    project = ProjectBrain("./hermes", name="hermes")
    counts = project.discover_and_load()
    print(f"Loaded modules: {counts}")

    context = await project.get_context("How do I handle blocked steps in a chain?")
    print(f"\nContext:\n{context[:500]}...")


if __name__ == "__main__":
    asyncio.run(example())
