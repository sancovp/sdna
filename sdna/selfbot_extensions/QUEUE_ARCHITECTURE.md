# Claude Queue System Architecture

## Vision

**One Claude, Many Tasks, Programmatic Continuity**

There is ONE chat channel (tmux session). We programmatically control:
- Which conversation is active
- When to /new, /resume, /compact
- What prompts get sent and when
- Continuity across sessions and compactions

The system is the **conductor**. Claude is the **musician**. One instrument, infinite compositions.

---

## Three Layers

### 1. Context Engineering Layer
Controls the conversation lifecycle:
- `/new` - Start fresh conversation
- `/resume <id>` - Resume existing conversation
- `/compact` - Compress current context
- Conversation registry (which convos exist, their state)

**This layer answers:** "Which conversation should be active right now?"

### 2. Chat Channel Layer
The actual tmux session:
- Single point of interaction
- Sends prompts via `tmux send-keys`
- Receives completion signals via hooks
- ONE active conversation at a time

**This layer answers:** "How do I talk to Claude?"

### 3. Prompt Queue Layer
Tasks waiting to be processed:
- Queue of prompts (persistent JSON)
- Each prompt can specify: new/resume/continue, conversation_id, priority
- Processed sequentially (sync mode) or with concurrency rules (async mode)

**This layer answers:** "What should Claude do next?"

---

## Data Model

```python
@dataclass
class Conversation:
    id: str                    # Claude's conversation ID
    name: str                  # Human-readable name
    created_at: datetime
    last_active: datetime
    status: str                # "active" | "idle" | "compacted"
    context_tokens: int        # Estimated tokens used
    tags: list[str]            # For routing (e.g., ["etsy", "daily"])

@dataclass
class QueuedTask:
    id: str
    prompt: str
    status: str                # "pending" | "running" | "done" | "failed"

    # Routing
    conversation_mode: str     # "new" | "resume" | "continue" | "auto"
    conversation_id: str       # If resume, which one
    conversation_tags: list    # If auto, match by tags

    # Scheduling
    scheduled_at: datetime     # When to run (None = ASAP)
    priority: int              # Higher = sooner

    # Results
    started_at: datetime
    completed_at: datetime
    result: str                # Output or error
```

---

## Flow

```
                    ┌──────────────────┐
                    │   Prompt Queue   │
                    │  (pending tasks) │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Queue Processor │
                    │    (daemon)      │
                    └────────┬─────────┘
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
    ┌───────────┐    ┌───────────┐    ┌───────────┐
    │ /new      │    │ /resume   │    │ continue  │
    │           │    │ <id>      │    │ (as-is)   │
    └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                    ┌──────────────────┐
                    │  Chat Channel    │
                    │  (tmux session)  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │     Claude       │
                    │  (processing)    │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Completion Hook │
                    │  (signals done)  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Task Completed  │
                    │  → next in queue │
                    └──────────────────┘
```

---

## Conversation Routing Modes

### `new`
Start a fresh conversation. Use for:
- Unrelated tasks
- Tasks that need clean context
- Daily fresh starts

### `resume`
Resume a specific conversation by ID. Use for:
- Continuing a project
- Multi-session work
- Picking up where you left off

### `continue`
Keep current conversation. Use for:
- Related follow-up tasks
- Same-context work
- Batching similar tasks

### `auto`
System decides based on:
- Task tags match conversation tags
- Context utilization (if near limit, /new or /compact)
- Time since last activity
- Explicit routing rules

---

## Completion Detection

How do we know Claude finished a task?

### Chosen: Tmux Buffer + Regex Marker

Every CRON prompt includes:
```
When task is complete, respond with: <CRON>DONE</CRON>
```

Processor polls tmux buffer:
```bash
tmux capture-pane -t cave -p | grep -q "<CRON>DONE</CRON>"
```

When marker found → task complete → clear marker area → next task.

**Why this approach:**
- No hook dependency
- Simple polling
- Claude naturally responds with marker
- Can extend marker: `<CRON>DONE:success</CRON>` or `<CRON>DONE:error:reason</CRON>`

### Prompt Template

All CRON-scheduled prompts get wrapped:
```
[CRON TASK - ID: {task_id}]

{actual_prompt}

IMPORTANT: When this task is complete, end your response with exactly:
<CRON>DONE</CRON>

Also consider using autopoiesis to maintain yourself.
```

### Future: Flight Integration
CRON tasks could trigger flights instead of raw prompts. The processor would:
1. `/resume` or `/new` to right conversation
2. Start waypoint journey for the task's flight config
3. Poll for `<CRON>DONE</CRON>` as flight completes

---

## Context Management Rules

### When to /compact
- Context > 80% of limit
- Before starting a task that needs room
- Explicit schedule (e.g., every 10 tasks)

### When to /new
- Context > 95% (compaction won't save it)
- Task explicitly requests fresh context
- Conversation tags don't match task tags

### When to /resume
- Task specifies conversation_id
- Task tags match a sleeping conversation
- Continuing a project

---

## Sync Mode (MVP)

Single-threaded processing:
1. Get next task from queue
2. Handle conversation routing (/new, /resume, or continue)
3. Send prompt
4. Wait for completion signal
5. Mark task done
6. Repeat

No concurrency. No race conditions. Simple.

---

## Files

```
/tmp/agent_queue/
├── queue.json           # Pending tasks
├── conversations.json   # Known conversations
├── history/             # Completed tasks
│   └── {task_id}.json
└── signals/
    └── task_complete    # Hook writes here
```

---

## CLI

```bash
# Add task to queue
queue add "Write a tweet about AI" --mode new --priority 5

# Add task for specific conversation
queue add "Continue the analysis" --resume conv_abc123

# Add scheduled task
queue add "Daily standup summary" --schedule "0 9 * * *"

# List queue
queue list

# Process queue (daemon mode)
queue process

# Process single task
queue next
```

---

## Integration Points

### Hooks Needed
- **Notification/Stop** → Signal task completion
- **PreCompact** → Update context_tokens estimate

### Existing Infrastructure
- `agent_cron.py` → Scheduling (cron + one-shot)
- `get_tmux_session()` → Session detection
- `start_cave.sh` → Boot Claude if needed

---

## Future: Async Mode

Multiple conversations, smarter routing:
- Conversation pool (N active conversations)
- Task affinity (task X always goes to conv Y)
- Load balancing
- Parallel processing (multiple Claude instances)

But sync mode first. Get it working, then optimize.
