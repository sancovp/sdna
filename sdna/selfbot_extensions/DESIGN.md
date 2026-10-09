# selfbot — DESIGN

The system that turns expensive exploration into cheap, reusable, self-healing
site SDKs.

```
find out how to do a thing  ->  EXPLORE   expensive, once, via computer use
encode in selfbot           ->  RECORD    the witnessed trace
make function               ->  COMPILE   typed callable + its replay test
sdk for xyz site            ->  LIBRARY   composed, versioned, per-site
```

**Computer use is not the product. It is the discovery channel. The SDK is the
product.**

## 1. The problem this exists to solve

Every general computer-use system has **no procedure memory**. Each run
re-derives "how do I list an item on this site" from pixels, from zero, forever.
They pay the full exploration price on every invocation and accumulate nothing.
That is the defect — not the click accuracy, not the model, not the browser.

selfbot pays exploration **once** and amortizes it. An agent that has an SDK
does not look at a screenshot; it calls `etsy.list_item(title=..., price=...)`.

The economics are the argument: a screenshot loop costs thousands of tokens and
several fallible reasoning steps per interaction, and produces nothing durable.
A compiled call costs one function invocation and cannot get lost.

## 2. The lifecycle

A `Procedure` is a verified way to do ONE action on ONE site. It moves through
exactly one lifecycle, and the transitions are asymmetric on purpose.

```
CANDIDATE ──green replay──> QUARANTINE ──human promote──> GOLDEN
    ^                                                       │
    │                                                       │ replay fails N×
    └────────── re-explore ────────── DEMOTED <─────────────┘
```

| status | meaning | who moves it |
|---|---|---|
| `CANDIDATE` | recorded from an exploration, never replayed | recorder |
| `QUARANTINE` | replayed green ≥1, awaiting a human | runtime, automatically |
| `GOLDEN` | promoted; compiled into the SDK; callable | **a named human, only** |
| `DEMOTED` | was golden, replay failed; back to the explore lane | immune system, automatically |
| `ARCHIVED` | deliberately retired | human |

**Only GOLDEN procedures compile.** A candidate is a hypothesis, not a library
function.

## 3. The three laws

These are enforced in code, not by convention — a rule that only lives in prose
is a rule that gets skipped at 2am.

### Law 1 — selectors, never coordinates

`Step.__post_init__` **rejects** a coordinate-shaped selector. A compiled
procedure that clicks `(847, 392)` is broken the instant anything moves, and it
breaks *silently*. Pixels are for exploring; selectors are for compiling.

The recorder's selector heuristic (`recorder.SELECTOR_JS`) is the substance
here: `data-testid` → stable `id` → `[name]` → `aria-label` → `text=` →
structural path. Generated ids (long hex, `ember-`/`react-`/`radix-` prefixes)
are rejected as unstable.

### Law 2 — promotion is human-only

`Procedure.promote(verified_by)` refuses without a named human, and refuses a
procedure that has never replayed green. A procedure can pass a thousand
replays and still sit in QUARANTINE forever. Nothing in the system can promote
itself.

This mirrors the ecosystem's existing promotion gates (golden cave-teams
configs, `convo-phase-ir`'s `promote_motif(verified_by)`).

### Law 3 — every procedure carries a checkable postcondition

`validate()` refuses to compile without one, and `SdkBuilder.finish()` refuses
to *record* without one — the failure lands while the exploration is still
fresh, which is the only moment anyone actually knows what "it worked" looked
like.

**This is the law the whole design turns on.** Sites change. Without a
postcondition, the failure mode is not an exception — it is `etsy.list_item()`
reporting success while listing nothing, for weeks. The postcondition is the
only thing that distinguishes success from silent breakage.

## 4. The immune system

`ImmuneSystem.sweep()` replays every golden procedure, demotes ones that fail
`failure_threshold` times consecutively (default 2 — sites have bad minutes),
and recompiles the affected site's SDK so a broken function stops being
importable rather than lingering as a trap.

The asymmetry restated, because it is the safety property:

- **demotion is automatic** — removing a broken thing is safe and reversible
- **promotion is human-only** — adding a trusted thing is an attestation

So the immune system can take a procedure *out* of the SDK and can never put
one back. A demoted procedure re-enters the explore lane with its provenance
(including the saved raw trace) intact, so re-exploration starts warm.

**"Never checked" and "broken" are different facts.** A golden procedure with
no `replay_args` is reported as `skipped`, never as `failed` — collapsing those
would make the sweep lie. Likewise `fire_replay_sweep` with no `driver_factory`
reports every procedure as unverified rather than claiming a clean sweep.

## 5. The join to the rest of the ecosystem

`Procedure.code_pointer` returns `sdk.<site>.<action>` — **exactly the shape
`AutomationSchema.code_pointer` already imports and calls**
(`domain/automation.py::get_code_callable`).

A compiled procedure is therefore schedulable the moment it exists, with zero
new plumbing:

```json
{"name": "list_weekly_batch",
 "schedule": "0 9 * * 1",
 "code_pointer": "sdk.etsy.list_item",
 "code_args": {"title": "...", "price": 12.0}}
```

And the immune sweep is itself a `CronAutomation`, following the established
`fire_*` convention (`blackbox.rollup.fire_usage_rollup`,
`cave_discord.sync.fire_role_sync`):

```json
{"name": "selfbot_replay_sweep",
 "schedule": "0 4 * * *",
 "code_pointer": "selfbot.application.immune.fire_replay_sweep"}
```

**The scheduler selfbot already had is what keeps the SDK true.** That is not a
coincidence — it is why selfbot has a scheduler.

## 6. Layers

Onion architecture, unchanged from the original selfbot: domain says WHAT,
infrastructure says HOW, application orchestrates, factory wires.

| module | layer | what it is for |
|---|---|---|
| `domain/procedure.py` | domain | `Procedure`/`Step`/`ArgSpec`/`Condition`/`Provenance` + the `PageDriver` and `ProcedureRepository` protocols. Pure, stdlib only. Laws 1–3 live here. |
| `domain/procedure_codegen.py` | domain | Procedure → typed SDK function **+ its replay test**. Sibling of `automation_codegen.py`. |
| `infrastructure/procedure_runtime.py` | infra | Executes a Procedure against a `PageDriver`; `PlaywrightDriver`; `replay()`. |
| `infrastructure/recorder.py` | infra | `TraceRecorder`, `RecordingDriver`, injected-JS selector capture. |
| `infrastructure/procedure_storage.py` | infra | JSON + in-memory `ProcedureRepository`. |
| `application/sdk_builder.py` | app | The pipeline surface: begin → finish → verify → promote → compile. |
| `application/immune.py` | app | Replay sweeps, demotion, `fire_replay_sweep`. |
| `domain/models.py`, `application/*`, `infrastructure/*` | — | the pre-existing selfbot: scheduled script execution in isolated Xvfb screens. |

`PageDriver` is deliberately tiny — ten methods. That is the entire surface a
compiled procedure needs, which is why swapping the browser underneath
(Playwright → CloakBrowser → anything) is a one-adapter change.

## 7. Recording: exploration and recording are the same act

`RecordingDriver` wraps a real `PageDriver` and records every call. An agent
explores *through* it and the trace falls out for free — there is no separate
"now write it down" step to forget.

```python
builder.begin("etsy", "list_item", inner_driver=PlaywrightDriver(page))
builder.driver.navigate("https://etsy.com/...")   # recorded
builder.driver.fill("#title", "Blue Mug")         # recorded
builder.recorder.parameterize("Blue Mug", "title")  # INVERT: literal -> $arg
builder.finish(postcondition=Condition(selector=".listing-active"))
```

`parameterize()` is the **INVERT** step in vajra terms: the recorded trace was
one concrete run, and naming its literals is what turns a locked seed into a
generator.

For directly-driven browsers (a human logging in, or a pixel-clicking agent),
`attach_recorder(page)` / `drain_recorder(page)` capture interactions via
injected JS using the same selector heuristic.

## 8. Why generated code is thin

Generated functions delegate to `run_procedure` rather than inlining logic, and
embed a **frozen** JSON copy of the procedure spec rather than reading the
repository at call time.

Frozen because the SDK must be what a human promoted, and must not change
underneath them because someone edited a stored procedure. Recompiling is an
explicit act with a diff. Thin because a human has to read the generated file
when a site breaks, and machinery that lives in one place gets fixed once.

## 9. Canonical location, and the name

`sanctuary-revolution-alpha/base/sdna/sdna/selfbot_extensions` is the
**canonical, hot** copy. The container copy at
`/tmp/heaven_data/skills/use-computer/resources/selfbot` is a **deploy target**,
never edited by hand.

The package previously existed *only* in that container — untracked, ungitted,
invisible to every session, one `docker prune` from gone. It was ported here
whole (law 0: the monorepo is the only canonical home), `SKILL.md` and
`scripts/computer.sh` included, since the skill and the library are one
artifact.

### Why it lives inside sdna, and why it is not called `selfbot`

**`sdna.selfbot` already exists and is a different thing.** It is 183 lines of
agent self-prompting via `tmux send-keys` — `SelfBot.prompt(text, session=...)`,
exported from `sdna/__init__.py`. Same word, unrelated referent: that one
injects text into a terminal session; this one drives GUI applications in
isolated Xvfb screens and compiles site procedures into SDKs.

They are homonyms, not versions. Hence `selfbot_extensions` (Isaac's naming,
2026-08-10).

It lives *inside* sdna because that is where the automation family already is
(`sdna/cron.py`, `sdna/selfbot.py`, `Heartbeat`), and because this package
already imported `sdna.context_engineering` — as a sibling that was a
cross-package dependency; as a subpackage it is an ordinary internal import.

**The packaging cost is paid by extras, not by sdna's users.** `jinja2`,
`pillow` and `playwright` are declared under `[selfbot]` / `[browser]`, so a
plain `pip install sanctuary-dna` remains a DSL install with no browser stack:

```
pip install sanctuary-dna              # the DSL, unchanged
pip install sanctuary-dna[selfbot]     # + codegen and virtual screens
pip install sanctuary-dna[browser]     # + Playwright driving
```

⚠ `sdna` has no `DESIGN.md`. Rule 26 wants one canonical design per PROJECT,
which would make this file a *section* of sdna's. Writing sdna's design is
architecture and is Isaac's; until it exists this file stands alone and rolls
up when it does.

## 10. Status

**BUILT + VERIFIED** — 38/38 tests, no browser required (`FakeDriver`
implements `PageDriver` over a dict, so the whole pipeline including generated
code *executing* is proven in CI).

`ASPIRATIONAL:` the pieces not yet built —

- **No site has been instantiated.** The layer is complete and the first real
  procedure has not been recorded. Nothing is verified against a live site.
- **Persistent authenticated profiles** — log in once by hand, agent inherits
  the session. This is the practical answer to CAPTCHA friction (established
  sessions do not trigger challenges the way fresh suspicious logins do) and is
  not built.
- **CloakBrowser adapter** — a drop-in Playwright replacement with C++-level
  fingerprint patches. Worth adding *if and when* a specific target blocks a
  legitimate automation; it is a proprietary, subscription-gated binary that
  auto-downloads at install, so it belongs in an isolated container and never
  alongside the carton graph. Not adopted speculatively.
- **An open-source computer-use agent as the explorer** — the agent that explores a site or a desktop app
  (today the `use-computer` skill's screenshot-and-xdotool loop) replaced by a better open-source one, driving
  a Playwright page through `RecordingDriver` or an Xvfb `Screen`, so its exploration still compiles. Which one
  is not chosen.
- **Installed in a JobWorld box** — Xvfb, xdotool, a browser, the `[selfbot,browser]` extras and the skill in
  the JobWorld image, so every business's agents have computer use (`application/jobworld/DESIGN.md` §1).
- **CLI** — `selfbot procedure list/promote/compile` alongside the existing
  `selfbot.cli`.
- **Carton projection** — golden procedures as graph concepts, so procedure
  knowledge is queryable rather than only importable.
