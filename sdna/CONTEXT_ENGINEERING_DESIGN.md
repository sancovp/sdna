# Context Engineering Library Design

## Purpose

Bridge SDK and tmux paradigms so higher layers (SDNA chains, selfbot, CAVEAgent) don't care about transport. Enables context surgery (inject, weave, dovetail) to work across both.

## Architecture

```
CAVEAgent / Selfbot / SDNA Chains
    - Call ContextEngineeringLib
    - Don't know/care about transport
                 ↓
ContextEngineeringLib
    - Unified session interface
    - Context surgery operations
    - Auto-detects or explicit transport selection
        ↓                   ↓
TmuxTransport           SDKTransport
    - send_keys()           - claude_agent_sdk
    - capture_pane()        - session management
    - session mgmt          - programmatic calls
        ↓                   ↓
Claude (Code or API)
```

## Session Model

A "session" abstracts over:
- tmux: tmux session name (e.g., "cave", "claude")
- SDK: conversation_id from Claude Agent SDK

## Core Operations

1. Session Discovery: list_sessions(), get_active_session(), get_session(id)
2. Context Surgery: inject(), weave(), dovetail()
3. Prompt Execution: send(), send_chain()
4. State Management: get_session_state(), save_session_state()

## Inject Methods

| Method | How it works | Best for |
|--------|--------------|----------|
| prepend | Prepend context to prompt | Simple injection |
| file | Write to file, reference in prompt | Large context |
| rules | Write to claude rules dir | Persistent context |
| env | Set environment variables | Config values |

## Weave Mechanics

1. tmux: Capture pane history, parse messages, extract range
2. SDK: Read conversation from transcript JSONL
3. Both: Optionally summarize before injecting to save tokens

## State Files

/tmp/context_engineering/
├── sessions.json           # Session registry
├── active_session.txt      # Current active session ID
├── state/{session_id}.json # Per-session state
└── weave_cache/{hash}.json # Cached weave results

## Integration Points

- Ariadne: WeaveConfig/InjectConfig.execute() calls lib methods
- Selfbot: queue_processor uses lib for sending
- Self-Claude: restart handler uses lib for state preservation

## Auto-Detection Logic

1. Check if tmux session exists (cave or claude)
2. Check if SDK is importable
3. Default to tmux (most common for Claude Code)
