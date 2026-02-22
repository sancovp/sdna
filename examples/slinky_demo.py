#!/usr/bin/env python3
"""
Slinky Context Demo - Mock GIINT Project Test

Demonstrates:
1. Creating a mock GIINT project with features/components/deliverables/tasks
2. Starting Slinky watcher on a session file
3. Simulating task completions to trigger compression
4. Checking compression status

Usage:
    python examples/slinky_demo.py
"""

import json
import os
import tempfile
import time
from pathlib import Path
from datetime import datetime

# Add parent to path for local dev
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from sdna.slinky_manager import (
    GiintIntegration, SlinkyWatcher, SlinkyRollup,
    start_slinky, stop_slinky, get_slinky_status
)


def create_mock_giint_project(registry_path: Path) -> dict:
    """Create a mock GIINT project structure."""
    project = {
        "test_project": {
            "project_id": "test_project",
            "project_type": "single",
            "project_dir": "/tmp/test_project",
            "mode": "execution",
            "features": {
                "authentication": {
                    "feature_name": "authentication",
                    "components": {
                        "oauth_integration": {
                            "component_name": "oauth_integration",
                            "deliverables": {
                                "oauth_config": {
                                    "deliverable_name": "oauth_config",
                                    "tasks": {
                                        "write_config": {
                                            "task_id": "write_config",
                                            "status": "ready",
                                            "assignee": "AI",
                                            "agent_id": "cave-agent",
                                            "key_insight": None,
                                            "files_touched": None
                                        },
                                        "validate_config": {
                                            "task_id": "validate_config",
                                            "status": "ready",
                                            "assignee": "AI",
                                            "agent_id": "cave-agent",
                                            "key_insight": None,
                                            "files_touched": None
                                        }
                                    }
                                },
                                "oauth_handler": {
                                    "deliverable_name": "oauth_handler",
                                    "tasks": {
                                        "implement_handler": {
                                            "task_id": "implement_handler",
                                            "status": "ready",
                                            "assignee": "AI",
                                            "agent_id": "cave-agent",
                                            "key_insight": None,
                                            "files_touched": None
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
    }
    
    with open(registry_path, 'w') as f:
        json.dump(project, f, indent=2)
    
    return project


def complete_task(registry_path: Path, feature: str, component: str, 
                  deliverable: str, task_id: str, key_insight: str, 
                  files_touched: list) -> None:
    """Mark a task as done with metadata."""
    with open(registry_path, 'r') as f:
        projects = json.load(f)
    
    task = projects["test_project"]["features"][feature]["components"][component]["deliverables"][deliverable]["tasks"][task_id]
    task["status"] = "done"
    task["key_insight"] = key_insight
    task["files_touched"] = files_touched
    task["updated_at"] = datetime.now().isoformat()
    
    with open(registry_path, 'w') as f:
        json.dump(projects, f, indent=2)
    
    print(f"  ✅ Task '{task_id}' marked DONE")


def create_mock_session(session_path: Path, num_iterations: int = 5) -> None:
    """Create a mock Claude session file with multiple iterations."""
    lines = []
    
    for i in range(num_iterations):
        # User message
        user_msg = {
            "type": "user",
            "message": {
                "role": "user",
                "content": f"Iteration {i+1}: Please implement the feature..."
            },
            "timestamp": datetime.now().isoformat()
        }
        lines.append(json.dumps(user_msg))
        
        # Assistant response with thinking and tool use
        assistant_msg = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": f"Let me think about iteration {i+1}... " * 50
                    },
                    {
                        "type": "text",
                        "text": f"I'll implement the feature for iteration {i+1}. " * 20
                    },
                    {
                        "type": "tool_use",
                        "id": f"tool_{i}",
                        "name": "write_file",
                        "input": {"path": f"/tmp/file_{i}.py", "content": "# Code " * 100}
                    }
                ]
            },
            "timestamp": datetime.now().isoformat()
        }
        lines.append(json.dumps(assistant_msg))
        
        # Tool result
        tool_result = {
            "type": "user",
            "isMeta": True,
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"tool_{i}",
                        "content": f"File written successfully. " * 50
                    }
                ]
            },
            "timestamp": datetime.now().isoformat()
        }
        lines.append(json.dumps(tool_result))
    
    with open(session_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    
    # Calculate size
    size_bytes = session_path.stat().st_size
    print(f"  📝 Created mock session: {size_bytes:,} bytes, {num_iterations} iterations")


def main():
    print("=" * 60)
    print("🗜️  SLINKY CONTEXT DEMO - GIINT Integration")
    print("=" * 60)
    print()
    
    # Create temp directory for demo
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        registry_path = tmpdir / "projects.json"
        session_path = tmpdir / "session.jsonl"
        
        # Step 1: Create mock GIINT project
        print("📋 Step 1: Create mock GIINT project")
        create_mock_giint_project(registry_path)
        print(f"  Created: {registry_path}")
        print()
        
        # Step 2: Create mock session
        print("📝 Step 2: Create mock session file")
        create_mock_session(session_path, num_iterations=8)
        print()
        
        # Step 3: Initialize GIINT integration
        print("🔗 Step 3: Initialize GIINT integration")
        giint = GiintIntegration(registry_path=registry_path)
        print(f"  Watching: {registry_path}")
        print(f"  Signal file: {giint.signal_file}")
        print()
        
        # Step 4: Check initial state
        print("🔍 Step 4: Check initial state (no triggers)")
        trigger = giint.check_compression_trigger()
        print(f"  Trigger: {trigger}")
        print()
        
        # Step 5: Complete first task
        print("✏️  Step 5: Complete first task (not enough for deliverable)")
        complete_task(
            registry_path, 
            "authentication", "oauth_integration", "oauth_config", "write_config",
            key_insight="OAuth config uses PKCE flow",
            files_touched=["oauth_config.yaml"]
        )
        trigger = giint.check_compression_trigger()
        print(f"  Trigger: {trigger}")
        print()
        
        # Step 6: Complete second task → deliverable complete!
        print("✏️  Step 6: Complete second task → DELIVERABLE COMPLETE!")
        complete_task(
            registry_path,
            "authentication", "oauth_integration", "oauth_config", "validate_config",
            key_insight="Config validated against OAuth 2.1 spec",
            files_touched=["oauth_config.yaml", "validate.py"]
        )
        trigger = giint.check_compression_trigger()
        print(f"  🎯 Trigger: {trigger}")
        if trigger:
            summary = giint.build_summary_from_trigger(trigger)
            print(f"  📦 Summary: {summary}")
        print()
        
        # Step 7: Test manual signal
        print("🔔 Step 7: Test manual signal")
        signal_file = giint.signal_file
        signal_file.touch()
        print(f"  Created: {signal_file}")
        trigger = giint.check_compression_trigger()
        print(f"  🎯 Trigger: {trigger}")
        print()
        
        # Step 8: Run full Slinky watcher
        print("🚀 Step 8: Test SlinkyWatcher")
        
        # Reset GIINT state for full test
        giint2 = GiintIntegration(registry_path=registry_path)
        
        watcher = SlinkyWatcher(
            session_path=session_path,
            giint=giint2,
            token_threshold=50000  # Low threshold for demo
        )
        
        # Get initial size
        initial_chars = watcher._count_context_chars(
            open(session_path).readlines()
        )
        print(f"  Initial context: {initial_chars:,} chars (~{initial_chars//4:,} tokens)")
        
        # Complete the remaining task to trigger compression
        print("  Completing remaining task...")
        complete_task(
            registry_path,
            "authentication", "oauth_integration", "oauth_handler", "implement_handler",
            key_insight="Handler uses async/await for token refresh",
            files_touched=["oauth_handler.py", "token_manager.py"]
        )
        
        # Manual check (instead of background thread for demo)
        watcher._check_and_compress()
        
        # Check status
        status = watcher.get_status()
        print(f"  Status: {json.dumps(status, indent=4)}")
        
        # Check compressed file
        final_chars = watcher._count_context_chars(
            open(session_path).readlines()
        )
        print(f"  Final context: {final_chars:,} chars (~{final_chars//4:,} tokens)")
        print(f"  Compression: {initial_chars:,} → {final_chars:,} ({(1 - final_chars/initial_chars)*100:.1f}% reduction)")
        print()
        
        print("=" * 60)
        print("✅ Demo complete!")
        print("=" * 60)


if __name__ == "__main__":
    main()
