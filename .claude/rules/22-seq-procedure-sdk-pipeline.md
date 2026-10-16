# 22 — SEQ: the procedure→SDK pipeline (and its rehydration protocol)

REHYDRATION (read these, in this order, before working this feature):[
1. `base/sdna/sdna/selfbot_extensions/DESIGN.md` — the whole design; §3 (the three laws) is load-bearing
2. `base/sdna/sdna/selfbot_extensions/domain/procedure.py` — the domain object; the laws are enforced here
3. `base/sdna/sdna/selfbot_extensions/domain/procedure_codegen.py` — the compile step
4. `base/sdna/sdna/selfbot_extensions/application/sdk_builder.py` — the pipeline surface
5. `base/sdna/sdna/selfbot_extensions/application/immune.py` — the sweep that prevents silent rot
6. `base/sdna/tests/test_selfbot_extensions_pipeline.py` — every law has a test; read them as the spec
7. `base/sdna/sdna/selfbot_extensions/.claude/rules/selfbot_extensions_states.md` — what is open
]
NOT:[read the whole train doc for this feature — this list is the scoped set]

## The pipeline

```mermaid
sequenceDiagram
    actor Agent
    participant B as SdkBuilder
    participant R as TraceRecorder
    participant D as RecordingDriver
    participant Site as live site
    participant Repo as ProcedureRepository
    actor Human
    participant Gen as procedure_codegen
    participant SDK as sdk/<site>/

    Note over Agent,Site: EXPLORE — expensive, once
    Agent->>B: begin(site, action, inner_driver)
    B->>R: new TraceRecorder
    B->>D: wrap(inner_driver, recorder)
    loop until the agent figures it out
        Agent->>D: navigate / fill / click
        D->>Site: drive
        D->>R: record Step (selector, never coordinates)
    end
    Agent->>R: parameterize("Blue Mug", "title")
    Note right of R: INVERT — literal becomes $arg,<br/>one run becomes a generator

    Note over Agent,Repo: RECORD
    Agent->>B: finish(postcondition=...)
    B--xB: refuse if postcondition not checkable (LAW 3)
    B->>Repo: save Procedure (CANDIDATE)

    Note over B,Site: VERIFY
    Agent->>B: verify(site, action, driver, args)
    B->>Site: replay every step
    B->>B: check postcondition
    B->>Repo: save (CANDIDATE -> QUARANTINE if green)

    Note over Human,SDK: PROMOTE — human only (LAW 2)
    Human->>B: promote(site, action, verified_by="isaac")
    B--xB: refuse without a named human
    B->>Repo: save (GOLDEN)

    Note over B,SDK: COMPILE
    Agent->>B: compile()
    B->>Gen: generate_function(procedure)
    Gen--xGen: refuse if not GOLDEN
    Gen->>SDK: <action>.py (typed callable, frozen spec)
    Gen->>SDK: test_<action>_replay.py (the immune unit)

    Note over Agent,SDK: USE — cheap, forever
    Agent->>SDK: list_item(driver, title=..., price=...)
```

## The immune loop (what keeps it true)

```mermaid
sequenceDiagram
    participant Cron as CronAutomation
    participant I as ImmuneSystem
    participant Repo as ProcedureRepository
    participant Site as live site
    participant SDK as sdk/<site>/
    participant Q as explore queue

    Cron->>I: fire_replay_sweep()  (code_pointer)
    I->>Repo: list_by_status(GOLDEN)
    loop each golden procedure
        alt no replay_args supplied
            I->>I: SKIPPED — "never checked" ≠ "broken"
        else
            I->>Site: replay
            I->>I: check postcondition
            alt green
                I->>Repo: consecutive_failures = 0
            else red
                I->>Repo: consecutive_failures += 1
                alt >= failure_threshold
                    I->>Repo: demote(reason)
                    I->>SDK: recompile site without it
                    I->>Q: needs_reexploration() — provenance intact
                end
            end
        end
    end
    Note over I,Q: demotion AUTOMATIC (safe, reversible)<br/>promotion HUMAN-ONLY (an attestation)
```

TRIGGER:[working on the procedure/SDK layer · adding a site · a golden procedure
demoted and needs re-exploration · changing the codegen templates · about to
add a browser adapter behind `PageDriver`]
