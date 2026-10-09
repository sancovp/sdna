"""
Procedure Code Generator - Generates typed SDK functions from Procedures.

Sibling of automation_codegen. That one compiles a scheduled prompt into a
class; this one compiles a verified procedure into a callable:

    Procedure(site="etsy", action="list_item")
        -> sdk/etsy/list_item.py     :: list_item(title: str, price: float)
        -> sdk/etsy/test_list_item.py :: the replay test that keeps it honest

Two files, always, together. A generated function without its replay test is
the thing that rots silently, so the generator does not offer the option.

The generated function embeds a FROZEN copy of the procedure spec rather than
reading it from the repository at call time. That is deliberate: the SDK is
what a human promoted, and it must not change underneath them because someone
edited a stored procedure. Recompiling is an explicit act with a diff.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from jinja2 import Template

from .procedure import Procedure, ProcedureStatus, ArgType

# Where generated SDK packages live
DEFAULT_SDK_DIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "selfbot" / "sdk"


FUNCTION_TEMPLATE = Template('''"""
{{ site }}.{{ action }} - auto-generated SDK function.

{{ description }}

Generated: {{ generated_at }}
Procedure: {{ procedure_id }} v{{ version }}
Promoted by: {{ promoted_by }}{% if promoted_at %} on {{ promoted_at }}{% endif %}

DO NOT EDIT BY HAND. This file is compiled from a promoted Procedure. To change
it, re-explore the procedure and recompile - otherwise the SDK and the recorded
procedure drift apart, and the replay test starts testing the wrong thing.
"""

import json
from typing import Any, Dict, Optional

from sdna.selfbot_extensions.domain.procedure import Procedure
from sdna.selfbot_extensions.infrastructure.procedure_runtime import run_procedure

# Frozen at compile time. See module docstring. Kept as JSON rather than a
# Python literal so it diffs cleanly against the stored procedure.
PROCEDURE_SPEC = json.loads(r"""
{{ spec_json }}
""")

PROCEDURE = Procedure.from_dict(PROCEDURE_SPEC)
CODE_POINTER = "{{ code_pointer }}"


def {{ action }}(driver, *{% for a in args %}, {{ a.name }}: {{ a.python_type }}{% if not a.required %} = {{ a.default_repr }}{% endif %}{% endfor %}) -> Dict[str, Any]:
    """
    {{ description or "Run the " + site + "." + action + " procedure." }}

{% for a in args %}    :param {{ a.name }}: {{ a.description or "(no description recorded)" }}
{% endfor %}    :param driver: a PageDriver (e.g. PlaywrightDriver(page))
    :returns: dict of extracted values{% if returns %} - {{ returns_doc }}{% endif %}

    :raises PreconditionFailed: the page was not where this procedure starts
    :raises StepFailed: a step could not be executed
    :raises PostconditionFailed: steps ran but the outcome did not happen
    """
    return run_procedure(PROCEDURE, driver, {
{% for a in args %}        "{{ a.name }}": {{ a.name }},
{% endfor %}    })


# Uniform entry point - lets a caller invoke any SDK function the same way.
def call(driver, **kwargs) -> Dict[str, Any]:
    """Invoke {{ action }} with keyword arguments."""
    return {{ action }}(driver, **kwargs)
''')


REPLAY_TEST_TEMPLATE = Template('''"""
Replay test for {{ site }}.{{ action }}.

Generated: {{ generated_at }}
Procedure: {{ procedure_id }} v{{ version }}

This is the immune system's unit. It runs the real procedure against the real
site and checks the postcondition. When it fails, the procedure is demoted out
of the SDK and back into the explore lane - which is the whole reason the SDK
does not rot silently as sites change.

Fill in REPLAY_ARGS with values that are safe to use repeatedly. A replay test
that creates real state every run is a test you will end up disabling.
"""

from typing import Any, Dict, Optional

from sdna.selfbot_extensions.domain.procedure import Procedure
from sdna.selfbot_extensions.infrastructure.procedure_runtime import replay

from .{{ action }} import PROCEDURE

# Arguments the replay runs with. Prefer values that are idempotent or that
# target a dedicated test fixture on the site.
REPLAY_ARGS: Dict[str, Any] = {
{% for a in args %}    "{{ a.name }}": {{ a.replay_placeholder }},  # {{ a.description or a.python_type }}
{% endfor %}}


def run_replay(driver) -> tuple:
    """
    Replay {{ site }}.{{ action }} and record the result on the procedure.

    Returns (ok, error, duration_seconds). Never raises.
    """
    return replay(PROCEDURE, driver, REPLAY_ARGS)


def test_{{ action }}_replay(driver=None):
    """
    pytest entry point. Skips when no driver is supplied, so the generated
    tests are collectable in environments with no browser.
    """
    if driver is None:  # pragma: no cover - environment dependent
        import pytest
        pytest.skip("no driver supplied; replay tests need a live browser")

    ok, error, _duration = run_replay(driver)
    assert ok, f"{{ site }}.{{ action }} replay failed: {error}"
''')


PACKAGE_INIT_TEMPLATE = Template('''"""
{{ site }} SDK - auto-generated.

Generated: {{ generated_at }}
Procedures: {{ count }}

Every function here was compiled from a Procedure that a human promoted to
GOLDEN. Call them instead of driving the site by hand:

{% for f in functions %}    from sdk.{{ site }} import {{ f }}
{% endfor %}
"""

{% for f in functions %}from .{{ f }} import {{ f }}
{% endfor %}
__all__ = {{ function_names }}

# name -> code_pointer, for scheduling any of these as an Automation.
CODE_POINTERS = {
{% for f in functions %}    "{{ f }}": "sdk.{{ site }}.{{ f }}",
{% endfor %}}
''')


def _default_repr(value, arg_type: ArgType) -> str:
    """Literal for an optional argument's default."""
    if value is None:
        return "None"
    return repr(value)


def _replay_placeholder(arg) -> str:
    """A visibly-fake default so an unfilled replay test fails loudly."""
    if arg.default is not None:
        return repr(arg.default)
    return {
        ArgType.STR: '"REPLACE_ME"',
        ArgType.PATH: '"/tmp/REPLACE_ME"',
        ArgType.INT: "0",
        ArgType.FLOAT: "0.0",
        ArgType.BOOL: "False",
    }[arg.type]


def _arg_context(procedure: Procedure) -> List[dict]:
    """Flatten ArgSpecs into what the templates need."""
    return [
        {
            "name": a.name,
            "python_type": a.python_type,
            "required": a.required,
            "description": a.description,
            "default_repr": _default_repr(a.default, a.type),
            "replay_placeholder": _replay_placeholder(a),
        }
        for a in procedure.args
    ]


def generate_function(
    procedure: Procedure,
    sdk_dir: Path = DEFAULT_SDK_DIR,
    require_golden: bool = True,
) -> tuple[Path, Path]:
    """
    Generate the SDK function and its replay test for one procedure.

    Returns (function_path, replay_test_path).

    Refuses non-golden procedures by default. Compiling a candidate would put
    an unverified procedure in the library, which is the one thing the
    quarantine lane exists to prevent.
    """
    if require_golden and procedure.status is not ProcedureStatus.GOLDEN:
        raise ValueError(
            f"{procedure.qualified_name} is {procedure.status.value}, not golden - "
            "only promoted procedures are compiled into the SDK"
        )

    problems = procedure.validate()
    if problems:
        raise ValueError(
            f"{procedure.qualified_name} is not compilable: " + "; ".join(problems)
        )

    site_dir = Path(sdk_dir) / procedure.site
    site_dir.mkdir(parents=True, exist_ok=True)

    args = _arg_context(procedure)
    context = {
        "site": procedure.site,
        "action": procedure.action,
        "description": procedure.description,
        "args": args,
        "returns": procedure.returns,
        "returns_doc": ", ".join(
            f"{k} ({v})" if v else k for k, v in procedure.returns.items()
        ),
        "spec_json": json.dumps(procedure.to_dict(), indent=4),
        "code_pointer": procedure.code_pointer,
        "procedure_id": procedure.id,
        "version": procedure.version,
        "promoted_by": procedure.promoted_by or "(unpromoted)",
        "promoted_at": (
            procedure.promoted_at.isoformat() if procedure.promoted_at else ""
        ),
        "generated_at": datetime.now().isoformat(),
    }

    function_path = site_dir / f"{procedure.action}.py"
    function_path.write_text(FUNCTION_TEMPLATE.render(**context))

    test_path = site_dir / f"test_{procedure.action}_replay.py"
    test_path.write_text(REPLAY_TEST_TEMPLATE.render(**context))

    return function_path, test_path


def generate_site(
    procedures: List[Procedure],
    site: str,
    sdk_dir: Path = DEFAULT_SDK_DIR,
    require_golden: bool = True,
) -> List[Path]:
    """
    Generate every function for one site and write the package __init__.

    Only golden procedures are included. Others are skipped with a note rather
    than raising, so one unpromoted procedure cannot block a whole site's SDK.
    """
    site_dir = Path(sdk_dir) / site
    site_dir.mkdir(parents=True, exist_ok=True)

    generated: List[Path] = []
    names: List[str] = []

    for procedure in procedures:
        if procedure.site != site:
            continue
        if require_golden and procedure.status is not ProcedureStatus.GOLDEN:
            print(f"  skip {procedure.qualified_name}: {procedure.status.value}")
            continue
        try:
            fn_path, test_path = generate_function(
                procedure, sdk_dir, require_golden=require_golden
            )
            generated.extend([fn_path, test_path])
            names.append(procedure.action)
            print(f"  generated {procedure.qualified_name}")
        except Exception as e:
            print(f"  failed {procedure.qualified_name}: {e}")

    init_path = site_dir / "__init__.py"
    init_path.write_text(PACKAGE_INIT_TEMPLATE.render(
        site=site,
        functions=names,
        function_names=repr(names),
        count=len(names),
        generated_at=datetime.now().isoformat(),
    ))
    generated.append(init_path)

    return generated


def generate_all(
    procedures: List[Procedure],
    sdk_dir: Path = DEFAULT_SDK_DIR,
    require_golden: bool = True,
) -> List[Path]:
    """Generate SDKs for every site represented in `procedures`."""
    sdk_dir = Path(sdk_dir)
    sdk_dir.mkdir(parents=True, exist_ok=True)

    sites = sorted({p.site for p in procedures})
    generated: List[Path] = []

    for site in sites:
        print(f"{site}:")
        generated.extend(generate_site(procedures, site, sdk_dir, require_golden))

    root_init = sdk_dir / "__init__.py"
    root_init.write_text(
        '"""Generated site SDKs."""\n\n'
        + "\n".join(f"from . import {s}" for s in sites)
        + f"\n\n__all__ = {sites!r}\n"
    )
    generated.append(root_init)

    return generated


# CLI
if __name__ == "__main__":
    import sys
    from ..infrastructure.procedure_storage import JsonProcedureRepository

    if len(sys.argv) < 2:
        print("Usage:")
        print("  procedure_codegen.py generate <site>.<action> [sdk_dir]")
        print("  procedure_codegen.py generate-site <site> [sdk_dir]")
        print("  procedure_codegen.py generate-all [sdk_dir]")
        sys.exit(1)

    cmd = sys.argv[1]
    repo = JsonProcedureRepository()

    if cmd == "generate" and len(sys.argv) >= 3:
        site, action = sys.argv[2].split(".", 1)
        proc = repo.get_by_name(site, action)
        if not proc:
            print(f"No such procedure: {sys.argv[2]}")
            sys.exit(1)
        out = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_SDK_DIR
        fn, test = generate_function(proc, out)
        print(f"Generated: {fn}\nGenerated: {test}")

    elif cmd == "generate-site" and len(sys.argv) >= 3:
        out = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_SDK_DIR
        paths = generate_site(repo.list_all(), sys.argv[2], out)
        print(f"\nGenerated {len(paths)} files")

    elif cmd == "generate-all":
        out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SDK_DIR
        paths = generate_all(repo.list_all(), out)
        print(f"\nGenerated {len(paths)} files")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
