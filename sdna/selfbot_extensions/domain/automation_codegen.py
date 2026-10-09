"""
Automation Code Generator - Generates Python classes from JSON schemas.

The quine that writes code for future you.
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# Where generated automation classes live
DEFAULT_OUTPUT_DIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "cave" / "automations"

CLASS_TEMPLATE = Template('''"""
{{ description or name }} - Auto-generated automation class.

Generated: {{ generated_at }}
Source: {{ source_json }}

You can subclass this to customize behavior:

    from {{ module_path }} import {{ class_name }}

    class My{{ class_name }}({{ class_name }}):
        def pre_execute(self, context):
            # Custom pre-hook
            pass
"""

from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass

# Base import - adjust if your package structure differs
try:
    from sdna.selfbot_extensions.domain.automation import Automation, AutomationSchema
except ImportError:
    # Fallback for standalone usage
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from sdna.selfbot_extensions.domain.automation import Automation, AutomationSchema


@dataclass
class {{ class_name }}Context:
    """Context passed to {{ class_name }} execution."""
    {% for var, value in template_vars.items() %}
    {{ var }}: str = "{{ value }}"
    {% endfor %}
    {% if not template_vars %}
    pass  # Add your context fields here
    {% endif %}


class {{ class_name }}(Automation):
    """
    {{ description or name }}

    Schedule: {{ schedule or 'manual' }}
    Session: {{ session_mode }} {% if session_id %}({{ session_id }}){% endif %}
    """

    NAME = "{{ name }}"
    SCHEDULE = {{ schedule_repr }}
    SESSION_MODE = "{{ session_mode }}"
    PRIORITY = {{ priority }}
    TAGS = {{ tags }}

    # Source JSON for reference
    SOURCE_JSON = Path("{{ source_json }}")

    def __init__(self, session_id: Optional[str] = {{ session_id_repr }}):
        """
        Initialize {{ class_name }}.

        Args:
            session_id: Override session for /resume. None = use schema default.
        """
        schema = AutomationSchema(
            name="{{ name }}",
            description="{{ description }}",
            schedule={{ schedule_repr }},
            prompt_template={{ prompt_template_repr }},
            {% if code_pointer %}
            code_pointer="{{ code_pointer }}",
            code_args={{ code_args }},
            {% endif %}
            template_vars={{ template_vars }},
            session_mode="{{ session_mode }}",
            session_id={{ session_id_repr }},
            priority={{ priority }},
            tags={{ tags }},
        )
        super().__init__(schema=schema, session_id=session_id)

    def pre_execute(self, context: {{ class_name }}Context) -> None:
        """Hook called before execution. Override to customize."""
        pass

    def post_execute(self, context: {{ class_name }}Context, result: dict) -> dict:
        """Hook called after execution. Override to customize result."""
        return result

    def build_context(self, **overrides) -> {{ class_name }}Context:
        """Build execution context with optional overrides."""
        return {{ class_name }}Context(**overrides)

    def execute(self, queue: 'TaskQueue' = None, **context_overrides) -> dict:
        """
        Execute this automation.

        Args:
            queue: TaskQueue to add prompt to
            **context_overrides: Override template variables

        Returns:
            Execution result dict
        """
        context = self.build_context(**context_overrides)
        self.pre_execute(context)

        # Merge context into template vars
        extra_vars = {k: getattr(context, k) for k in context.__dataclass_fields__}

        result = self.fire(queue, extra_vars=extra_vars)
        return self.post_execute(context, result)


# Convenience function for direct execution
def run(queue: 'TaskQueue' = None, session_id: Optional[str] = None, **kwargs) -> dict:
    """Run {{ name }} automation."""
    auto = {{ class_name }}(session_id=session_id)
    return auto.execute(queue, **kwargs)


if __name__ == "__main__":
    # Quick test
    auto = {{ class_name }}()
    print(f"Automation: {auto.name}")
    print(f"Schedule: {auto.schedule}")
    print(f"Session: {auto.get_session_mode()}")
    print(f"\\nPrompt preview:\\n{auto.render_prompt()[:500]}...")
''')


def to_class_name(name: str) -> str:
    """Convert snake_case to PascalCase."""
    return ''.join(word.capitalize() for word in name.split('_'))


def repr_str(value) -> str:
    """Return repr of value, handling None and strings."""
    if value is None:
        return "None"
    elif isinstance(value, str):
        # Use triple quotes for multiline
        if '\n' in value:
            return f'"""{value}"""'
        return repr(value)
    return repr(value)


def generate_class(
    schema_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    """
    Generate Python class from JSON schema.

    Args:
        schema_path: Path to automation JSON schema
        output_dir: Where to write generated .py file

    Returns:
        Path to generated Python file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load schema
    data = json.loads(schema_path.read_text())
    name = data['name']
    class_name = to_class_name(name)

    # Prepare template context
    context = {
        'name': name,
        'class_name': class_name,
        'description': data.get('description', ''),
        'schedule': data.get('schedule'),
        'schedule_repr': repr_str(data.get('schedule')),
        'prompt_template': data.get('prompt_template', ''),
        'prompt_template_repr': repr_str(data.get('prompt_template', '')),
        'code_pointer': data.get('code_pointer'),
        'code_args': data.get('code_args', {}),
        'template_vars': data.get('template_vars', {}),
        'session_mode': data.get('session_mode', 'main'),
        'session_id': data.get('session_id'),
        'session_id_repr': repr_str(data.get('session_id')),
        'priority': data.get('priority', 5),
        'tags': data.get('tags', []),
        'source_json': str(schema_path.absolute()),
        'generated_at': datetime.now().isoformat(),
        'module_path': f"cave.automations.{name}",
    }

    # Render template
    code = CLASS_TEMPLATE.render(**context)

    # Write output
    output_path = output_dir / f"{name}.py"
    output_path.write_text(code)

    # Also create __init__.py if missing
    init_path = output_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text('"""Generated automation classes."""\n')

    return output_path


def generate_all(
    schemas_dir: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Generate classes for all JSON schemas in directory."""
    generated = []
    for json_file in schemas_dir.glob("*.json"):
        try:
            path = generate_class(json_file, output_dir)
            generated.append(path)
            print(f"Generated: {path}")
        except Exception as e:
            print(f"Failed {json_file}: {e}")

    # Update __init__.py with imports
    update_init(output_dir, generated)
    return generated


def update_init(output_dir: Path, generated: list[Path]):
    """Update __init__.py with imports for all generated classes."""
    init_path = output_dir / "__init__.py"

    imports = ['"""Generated automation classes."""', '']
    all_names = []

    for path in generated:
        module_name = path.stem
        class_name = to_class_name(module_name)
        imports.append(f"from .{module_name} import {class_name}")
        all_names.append(class_name)

    imports.append('')
    imports.append(f"__all__ = {all_names}")

    init_path.write_text('\n'.join(imports))


# CLI
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  automation_codegen.py generate <schema.json> [output_dir]")
        print("  automation_codegen.py generate-all <schemas_dir> [output_dir]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "generate" and len(sys.argv) >= 3:
        schema = Path(sys.argv[2])
        output = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_OUTPUT_DIR
        path = generate_class(schema, output)
        print(f"Generated: {path}")

    elif cmd == "generate-all" and len(sys.argv) >= 3:
        schemas = Path(sys.argv[2])
        output = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_OUTPUT_DIR
        paths = generate_all(schemas, output)
        print(f"\nGenerated {len(paths)} automation classes")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
