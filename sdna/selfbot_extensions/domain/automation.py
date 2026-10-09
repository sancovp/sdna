"""
Automation - Base class for scheduled agent automations.

Schema-driven execution with optional code pointers and session routing.
"""

import json
import os
import importlib
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any, Callable
from string import Template

logger = logging.getLogger(__name__)


@dataclass
class AutomationSchema:
    """Schema loaded from JSON defining what an automation does."""
    name: str
    description: str = ""
    schedule: Optional[str] = None  # Cron expression

    # Execution options (at least one required)
    prompt_template: Optional[str] = None  # Prompt to send to Claude
    code_pointer: Optional[str] = None     # "module.func" to import and call
    code_args: dict = field(default_factory=dict)  # Args for code_pointer

    # Templating
    template_vars: dict = field(default_factory=dict)  # Variables for prompt_template

    # Context Engineering
    context_source: Optional[str] = None   # Session ID to weave context from
    context_range: tuple = (-5, -1)        # Default: last 5 messages
    context_config: Optional[dict] = None  # Static context to inject

    # Session routing
    session_mode: str = "main"  # "main" | "new" | "resume"
    session_id: Optional[str] = None  # For resume mode

    # Metadata
    priority: int = 5
    tags: list = field(default_factory=list)

    @classmethod
    def from_json(cls, path: Path) -> 'AutomationSchema':
        """Load schema from JSON file."""
        data = json.loads(path.read_text())
        return cls(**data)

    @classmethod
    def from_dict(cls, data: dict) -> 'AutomationSchema':
        """Create schema from dict."""
        return cls(**data)

    def to_dict(self) -> dict:
        """Export to dict."""
        return {
            "name": self.name,
            "description": self.description,
            "schedule": self.schedule,
            "prompt_template": self.prompt_template,
            "code_pointer": self.code_pointer,
            "code_args": self.code_args,
            "template_vars": self.template_vars,
            "context_source": self.context_source,
            "context_range": list(self.context_range),
            "context_config": self.context_config,
            "session_mode": self.session_mode,
            "session_id": self.session_id,
            "priority": self.priority,
            "tags": self.tags,
        }


class Automation:
    """
    Base automation class - loads schema and executes.

    Subclass to customize session routing or add pre/post hooks.
    """

    def __init__(
        self,
        schema: Optional[AutomationSchema] = None,
        schema_path: Optional[Path] = None,
        session_id: Optional[str] = None,  # Override schema's session
    ):
        if schema:
            self.schema = schema
        elif schema_path:
            self.schema = AutomationSchema.from_json(schema_path)
        else:
            raise ValueError("Must provide schema or schema_path")

        # Allow override of session routing
        if session_id is not None:
            self._session_id = session_id
        else:
            self._session_id = self.schema.session_id

    @property
    def name(self) -> str:
        return self.schema.name

    @property
    def schedule(self) -> Optional[str]:
        return self.schema.schedule

    @property
    def session_id(self) -> Optional[str]:
        """Session to use. None = main session."""
        return self._session_id

    @session_id.setter
    def session_id(self, value: Optional[str]):
        self._session_id = value

    def get_session_mode(self) -> str:
        """Determine session mode based on config."""
        if self.schema.session_mode == "new":
            return "new"
        elif self.schema.session_mode == "resume" and self._session_id:
            return "resume"
        else:
            return "continue"  # main session

    def render_prompt(self, extra_vars: Optional[dict] = None) -> Optional[str]:
        """Render prompt template with variables, including woven context."""
        if not self.schema.prompt_template:
            return None

        vars = {**self.schema.template_vars}
        if extra_vars:
            vars.update(extra_vars)

        # Weave context from another session if configured
        if self.schema.context_source:
            try:
                from sdna.context_engineering import get_lib

                lib = get_lib()
                source = lib.get_session(self.schema.context_source)
                target = lib.get_active_session()

                if source and target:
                    start, end = self.schema.context_range
                    result = lib.weave(source, target, start, end)
                    vars['woven_context'] = result.content
                    logger.info(f"Wove {result.token_estimate} tokens into prompt")
            except ImportError:
                logger.debug("context_engineering not available")
            except Exception as e:
                logger.warning(f"Context weaving failed: {e}")
                vars['woven_context'] = ""

        # Inject static context if configured
        if self.schema.context_config:
            try:
                from sdna.context_engineering import get_lib, InjectMethod

                lib = get_lib()
                session = lib.get_active_session()
                if session:
                    lib.inject(session, self.schema.context_config, InjectMethod.PREPEND)
            except ImportError:
                pass
            except Exception as e:
                logger.warning(f"Context injection failed: {e}")

        return Template(self.schema.prompt_template).safe_substitute(vars)

    def get_code_callable(self) -> Optional[Callable]:
        """Import and return the code pointer function."""
        if not self.schema.code_pointer:
            return None

        try:
            parts = self.schema.code_pointer.rsplit(".", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid code_pointer: {self.schema.code_pointer}")

            module_path, func_name = parts
            module = importlib.import_module(module_path)
            return getattr(module, func_name)
        except Exception as e:
            logger.exception(f"Failed to import {self.schema.code_pointer}: {e}")
            return None

    def execute_code(self, extra_args: Optional[dict] = None) -> Any:
        """Execute the code pointer with args."""
        func = self.get_code_callable()
        if not func:
            return None

        args = {**self.schema.code_args}
        if extra_args:
            args.update(extra_args)

        return func(**args)

    def fire(self, queue: 'TaskQueue' = None, extra_vars: Optional[dict] = None) -> dict:
        """
        Fire the automation.

        1. If code_pointer: execute code (may return prompt or modify state)
        2. If prompt_template: render and queue for Claude

        Returns execution result dict.
        """
        result = {
            "name": self.name,
            "code_result": None,
            "queued_task_id": None,
            "session_mode": self.get_session_mode(),
        }

        # Execute code if present
        if self.schema.code_pointer:
            try:
                result["code_result"] = self.execute_code(extra_vars)
            except Exception as e:
                logger.exception(f"Code execution failed: {e}")
                result["code_error"] = str(e)

        # Queue prompt if present
        if self.schema.prompt_template and queue:
            prompt = self.render_prompt(extra_vars)
            if prompt:
                from ..infrastructure.task_queue import ConversationMode

                mode_map = {
                    "new": ConversationMode.NEW,
                    "resume": ConversationMode.RESUME,
                    "continue": ConversationMode.CONTINUE,
                }
                mode = mode_map.get(self.get_session_mode(), ConversationMode.CONTINUE)

                task = queue.add(
                    prompt=prompt,
                    mode=mode,
                    conversation_id=self._session_id,
                    tags=self.schema.tags,
                    priority=self.schema.priority,
                    cron_expression=self.schema.schedule,
                )
                result["queued_task_id"] = task.id

        return result

    def __repr__(self):
        return f"Automation({self.name}, session={self._session_id or 'main'})"


class AutomationRegistry:
    """Registry of loaded automations."""

    def __init__(self, automations_dir: Optional[Path] = None):
        self.automations: dict[str, Automation] = {}
        self._dir = automations_dir or Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "automations"
        self._dir.mkdir(parents=True, exist_ok=True)

    def load_all(self):
        """Load all automation JSONs from directory."""
        for json_file in self._dir.glob("*.json"):
            try:
                auto = Automation(schema_path=json_file)
                self.automations[auto.name] = auto
                logger.info(f"Loaded automation: {auto.name}")
            except Exception as e:
                logger.exception(f"Failed to load {json_file}: {e}")

    def get(self, name: str) -> Optional[Automation]:
        """Get automation by name."""
        return self.automations.get(name)

    def register(self, automation: Automation):
        """Register an automation instance."""
        self.automations[automation.name] = automation

    def save_schema(self, schema: AutomationSchema) -> Path:
        """Save a schema to JSON file."""
        path = self._dir / f"{schema.name}.json"
        path.write_text(json.dumps(schema.to_dict(), indent=2))
        return path

    def list_all(self) -> list[str]:
        """List all automation names."""
        return list(self.automations.keys())
