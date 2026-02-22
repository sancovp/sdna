# Context Engineering Implementation Plan

## Phase 1: Core Infrastructure
- [ ] Implement inject() with PREPEND method
- [ ] Implement inject() with FILE method  
- [ ] Implement inject() with RULES method
- [ ] Test basic injection flow

## Phase 2: Weave Mechanics
- [ ] Implement tmux pane capture + message parsing
- [ ] Implement SDK conversation reading
- [ ] Implement weave() with range extraction
- [ ] Add optional summarization before inject
- [ ] Test weave between sessions

## Phase 3: Ariadne Integration
- [ ] Wire WeaveConfig.execute() to lib.weave()
- [ ] Wire InjectConfig.execute() to lib.inject()
- [ ] Implement send_chain() for full chain execution
- [ ] Test chains with context surgery

## Phase 4: Selfbot Integration
- [ ] Update queue_processor to use lib.send()
- [ ] Update automation.py for session routing
- [ ] Add context config to QueuedTask model
- [ ] Test automations with context injection

## Phase 5: Polish
- [ ] Implement dovetail()
- [ ] Add weave caching
- [ ] Add state persistence
- [ ] Error handling + logging
- [ ] Tests

## Files to Modify

| File | Changes |
|------|---------|
| sdna/context_engineering.py | Implement TODOs |
| sdna/ariadne.py | Wire execute() methods |
| selfbot/queue_processor.py | Use lib.send() |
| selfbot/automation.py | Add context routing |
| selfbot/task_queue.py | Add context to QueuedTask |
