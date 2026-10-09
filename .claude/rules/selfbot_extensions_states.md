# sdna.selfbot_extensions — open lanes

| lane | state | detail |
|---|---|---|
| procedure/SDK layer (domain, codegen, runtime, recorder, storage, builder, immune) | BUILT + VERIFIED 2026-08-10 — 38/38 tests, generated code executes, no browser needed | `DESIGN.md` §2–§8 |
| port from `mind_of_god:/tmp/heaven_data/skills/use-computer/resources` into the monorepo | DONE 2026-08-10 — canonical is `base/sdna/sdna/selfbot_extensions`; container copy is now a deploy target | `DESIGN.md` §9 |
| homed INSIDE sdna as `selfbot_extensions` (Isaac's ruling 2026-08-10; `sdna/selfbot.py` = the tmux self-prompter, a different thing sharing the name) | DONE 2026-08-10 — `[selfbot]`/`[browser]` extras keep the browser stack out of a plain `pip install sanctuary-dna` | `DESIGN.md` §9 |
| first real site instantiated (one procedure, recorded → promoted → compiled against a live site) | NOT STARTED — blocked on Isaac naming the site + first action | `DESIGN.md` §10 |
| persistent authenticated browser profile in the container | NOT STARTED — the practical answer to CAPTCHA friction; log in once by hand, agent inherits session | `DESIGN.md` §10 |
| CloakBrowser adapter behind `PageDriver` | NOT STARTED — deliberately deferred until a real target blocks a legitimate automation; proprietary subscription-gated binary, isolated container only | `DESIGN.md` §10 |
| an open-source computer-use agent as the explorer, recorded through `RecordingDriver` / `Screen` | NOT STARTED — which agent is not chosen | `DESIGN.md` §10 |
| installed in the JobWorld image (Xvfb · xdotool · a browser · the extras · the skill) | NOT STARTED | `DESIGN.md` §10 · `application/jobworld/DESIGN.md` §1 |
| `selfbot procedure` CLI (list / promote / compile) | NOT STARTED | `DESIGN.md` §10 |
| carton projection of golden procedures | NOT STARTED | `DESIGN.md` §10 |
| `sdna` has no `DESIGN.md` (rule 26: one per PROJECT) so this subpackage carries its own | AWAITING ISAAC — writing sdna's canonical DESIGN.md is architecture, not a cleanup pass; this rolls up as a section when it exists | rule 26 |
| non-`.py` files ship in the wheel (`scripts/computer.sh`, `SKILL.md`) | UNVERIFIED — hatch `packages = ["sdna"]` includes the subpackage's modules; the data files are not asserted | `pyproject.toml` |
| deploy path back into the container (sync monorepo → `use-computer` skill resources) | NOT STARTED — container currently holds the pre-port copy | `DESIGN.md` §9 |
