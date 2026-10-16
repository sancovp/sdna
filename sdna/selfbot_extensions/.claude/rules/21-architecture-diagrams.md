# selfbot_extensions — the stack

<docsys kind="arch-map" role="instance"/>

Drawn from `../../DESIGN.md` (§2–§9). Onion: the domain says WHAT, the infrastructure says HOW, the application
orchestrates; arrows are dependency direction (who calls whom); every external dependency ends at its seam.

```mermaid
flowchart TB
  classDef use fill:#ede7f6,stroke:#4527a0;
  classDef app fill:#e3f2fd,stroke:#1565c0;
  classDef dom fill:#fffde7,stroke:#f9a825;
  classDef infra fill:#e8f5e9,stroke:#2e7d32;
  classDef dep fill:#eceff1,stroke:#607d8b,stroke-dasharray:4 3;

  subgraph USE["WHO CALLS IT"]
    AGENT["an exploring agent — walks a site once through the recording driver (today the use-computer skill; an open-source computer-use agent · ASPIRATIONAL)"]:::use
    HUMAN["a named person of ours — the only one who promotes"]:::use
    SDK["the generated SDK — sdk/<site>/<action>.py, a typed function over a frozen spec, + its replay test (§8); a site only where its terms allow automation (§10)"]:::use
  end
  subgraph APP["application/ — orchestrates"]
    BUILDER["sdk_builder.py — begin → finish → verify → promote → compile (§7)"]:::app
    IMMUNE["immune.py — the sweep: replays every golden procedure, demotes after 2 failures, recompiles the site; fire_replay_sweep (§4)"]:::app
    OLD["the pre-existing selfbot — scheduled script execution in isolated screens (manager · runner · scheduler · the queue)"]:::app
  end
  subgraph DOM["domain/ — what a procedure IS; pure, stdlib only"]
    PROC["procedure.py — Procedure · Step · ArgSpec · Condition · Provenance; the PageDriver and ProcedureRepository protocols; the three laws enforced (§3) and the lifecycle (§2)"]:::dom
    GEN["procedure_codegen.py — a golden procedure → a typed function + its replay test"]:::dom
  end
  subgraph INFRA["infrastructure/ — how it happens"]
    RUN["procedure_runtime.py — run_procedure (precondition · steps · postcondition) · replay · PlaywrightDriver"]:::infra
    REC["recorder.py — TraceRecorder · RecordingDriver · the injected-JS selector capture"]:::infra
    STORE["procedure_storage.py — the JSON and in-memory ProcedureRepository"]:::infra
    SCREEN["virtual_screen/ — isolated Xvfb displays, N in parallel"]:::infra
  end
  PW["Playwright (the [browser] extra) · SEAM: a page, behind PageDriver's ten methods"]:::dep
  XVFB["Xvfb · xdotool · SEAM: a display number; scripts/computer.sh"]:::dep
  REG["an automation registry · SEAM: code_pointer sdk.<site>.<action> — a compiled function is schedulable as it lands (§5)"]:::dep

  AGENT -->|"explores through"| BUILDER
  HUMAN -->|"promote(verified_by)"| BUILDER
  BUILDER --> REC
  BUILDER --> STORE
  BUILDER -->|"verify: replay"| RUN
  BUILDER -->|"compile"| GEN
  GEN -->|"writes"| SDK
  SDK -->|"run_procedure"| RUN
  REC -->|"wraps a real driver"| RUN
  RUN -->|"implements PageDriver"| PROC
  STORE -->|"implements ProcedureRepository"| PROC
  GEN --> PROC
  IMMUNE -->|"replay"| RUN
  IMMUNE -->|"demote · recompile"| GEN
  RUN --> PW
  OLD --> SCREEN
  SCREEN --> XVFB
  REG -->|"fires"| IMMUNE
  REG -->|"fires"| SDK
```

## THE DEV FLOWS PLACED ON IT

| dev flow | where it runs on the map |
|---|---|
| `base/sdna/.claude/rules/22-seq-procedure-sdk-pipeline.md` — EXPLORE → RECORD → VERIFY → PROMOTE → COMPILE → USE, and the immune loop | `AGENT → BUILDER → REC`, `BUILDER → STORE`, `BUILDER → RUN`, `HUMAN → BUILDER`, `BUILDER → GEN → SDK`, `SDK → RUN`; the loop: `REG → IMMUNE → RUN`, `IMMUNE → GEN` |
