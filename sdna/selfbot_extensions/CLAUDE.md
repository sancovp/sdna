# sdna.selfbot_extensions

Turns expensive exploration into cheap, reusable, self-healing site SDKs:
`explore -> record -> compile -> library`. Computer use is the discovery
channel; the SDK is the product.

**Read `DESIGN.md` first**; its board is `.claude/rules/selfbot_extensions_states.md` and its stack
`.claude/rules/21-architecture-diagrams.md`. The three laws it states are enforced in code:
selectors never coordinates · promotion is human-only · every procedure carries
a checkable postcondition.

⚠ **NOT `sdna.selfbot`.** That is the tmux self-prompter (`SelfBot.prompt()`) —
same word, different thing. See `DESIGN.md` §9.

This dir is the CANONICAL home (law 0). The copy at
`/tmp/heaven_data/skills/use-computer/resources/selfbot` inside `mind_of_god`
is a deploy target — never hand-edit it.

- `domain/` — what a procedure/selfbot IS (pure, stdlib only)
- `application/` — the use cases (build an SDK, sweep for rot, run bots)
- `infrastructure/` — how it actually happens (browser, disk, screens)
- `virtual_screen/` — isolated Xvfb displays, N in parallel
- `scripts/` — `computer.sh`, the xdotool helper for GUI apps

Deps ride extras: `pip install sanctuary-dna[selfbot]` (codegen + screens) or
`[browser]` (+ Playwright). Tests: `python3 -m pytest tests/test_selfbot_extensions_pipeline.py -q`
from `base/sdna` (38, no browser needed).
