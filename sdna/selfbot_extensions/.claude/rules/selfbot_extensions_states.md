# selfbot_extensions — the state tables

> One design (`../../DESIGN.md`), N tables. A row is a deliverable; a column is a phase; `●` = reached.
> Detail hangs off by pointer. Notes go to the host scratchpad, never here.

## THE LANES

Phases: **DESIGNED** (stated in `DESIGN.md`) → **BUILT** (in the package, its tests green) → **PROVEN** (run against a
live site, its gate green).

| lane | DESIGNED | BUILT | PROVEN | detail |
|---|:-:|:-:|:-:|---|
| the procedure/SDK layer — domain, codegen, runtime, recorder, storage, builder, immune | ● | ● | | `../../DESIGN.md` §2–§8 |
| the canonical home is `base/sdna/sdna/selfbot_extensions`; the `mind_of_god` copy a deploy target | ● | ● | ● | `../../DESIGN.md` §9 |
| homed inside sdna as `selfbot_extensions`, the browser stack in the `[selfbot]` · `[browser]` extras | ● | ● | ● | `../../DESIGN.md` §9 |
| the first real site — one whose terms allow automation, read before its first procedure is recorded | ● | | | `../../DESIGN.md` §10 |
| a persistent signed-in browser profile | ● | | | `../../DESIGN.md` §10 |
| the CloakBrowser adapter behind `PageDriver` | ● | | | `../../DESIGN.md` §10 |
| an open-source computer-use agent as the explorer, recorded through `RecordingDriver` or a `Screen` | ● | | | `../../DESIGN.md` §10 |
| installed in the JobWorld image — Xvfb, xdotool, a browser, the extras, the skill | ● | | | `../../DESIGN.md` §10 · `application/jobworld/DESIGN.md` §1 |
| the `selfbot procedure` CLI — list, promote, compile | ● | | | `../../DESIGN.md` §10 |
| golden procedures projected onto CartON | ● | | | `../../DESIGN.md` §10 |
| the wheel ships the non-`.py` files (`scripts/computer.sh`, `SKILL.md`) | ● | ● | | `../../../../pyproject.toml` |
| the deploy path back into the container (monorepo → the `use-computer` skill's resources) | ● | | | `../../DESIGN.md` §9 |

## OPEN

Phases: **RAISED** → **PUT** (asked of *USER*) → **RULED** → **CLEARED** (the ruling written into the design).

| question | RAISED | PUT | RULED | CLEARED | detail |
|---|:-:|:-:|:-:|:-:|---|
| S1 · sdna has no `DESIGN.md` of its own (rule 26: one per project) — does sdna get one, with this design rolled up as its section? | ● | ● | | | `../../DESIGN.md` §9 |
