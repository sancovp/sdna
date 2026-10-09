# Computer Control Skill

**WHAT**: Control the virtual desktop (screenshot, mouse, keyboard) via xdotool/ImageMagick
**WHEN**: Need to interact with GUI applications, take screenshots, automate desktop tasks
**HOW**: Use the helper script or raw commands below

## Quick Start

```bash
# Screenshot (then Read /tmp/screen.png to view)
~/.claude/skills/use-computer/scripts/computer.sh screenshot

# Click at coordinates
~/.claude/skills/use-computer/scripts/computer.sh click 500 300

# Type text
~/.claude/skills/use-computer/scripts/computer.sh type "hello world"

# Press key (use Return, not Enter!)
~/.claude/skills/use-computer/scripts/computer.sh key Return
~/.claude/skills/use-computer/scripts/computer.sh key ctrl+c
```

## Display Stack Startup

If display is black/not working, start the stack in order:

```bash
# 1. Xvfb should already be running on :99
# 2. Start mutter (MUST use XDG_SESSION_TYPE=x11)
source ~/.display_env && XDG_SESSION_TYPE=x11 mutter --replace --sm-disable &

# 3. Now launch GUI apps
source ~/.display_env && firefox-esr &
```

Reference startup scripts: `/home/GOD/core/image/`

## Helper Script Reference

```bash
computer.sh screenshot [path]     # Take screenshot (default: /tmp/screen.png)
computer.sh click X Y             # Click at coordinates
computer.sh move X Y              # Move mouse to coordinates
computer.sh type "text"           # Type text
computer.sh key KEYNAME           # Press key (Return, ctrl+c, alt+Tab, etc)
computer.sh drag X1 Y1 X2 Y2      # Drag from (X1,Y1) to (X2,Y2)
computer.sh getmouse              # Get current mouse position
computer.sh getwindow             # Get active window name
computer.sh focuswindow NAME      # Focus window by name
computer.sh wait [SECS]           # Wait (default 1s)
```

## Key Gotchas

- **Use `Return` not `Enter`** for xdotool key presses
- **Use `import -window root`** not `scrot` for screenshots (mutter compositing)
- **Always `source ~/.display_env`** before raw commands
- **Start mutter before GUI apps** or windows won't render
- **Use keyboard nav** (Tab + Return) if clicks don't register

## Display Info

- Resolution: 1920x1080
- Display: :99
- Env file: `~/.display_env` (DISPLAY, WIDTH, HEIGHT, DISPLAY_NUM)
- View via noVNC: port 6080
- VNC: port 5900

## Raw Commands

```bash
# Screenshot (use import, not scrot!)
source ~/.display_env && import -window root /tmp/screen.png

# Mouse/keyboard
source ~/.display_env && xdotool mousemove 500 300 click 1
source ~/.display_env && xdotool type 'text'
source ~/.display_env && xdotool key Return

# Debug - list all windows
source ~/.display_env && xwininfo -root -tree | head -30
```

## Workflow Pattern

1. `screenshot` - see current state
2. Identify target coordinates from screenshot
3. `click`/`type`/`key` as needed (or Tab+Return for buttons)
4. `screenshot` - verify result

## Original Computer Use Code

Full implementation reference: `/home/GOD/core/computer_use_demo/tools/base/tools/computer_tool.py`

---

# Advanced: Virtual Screen Library + Selfbot System

Located in `resources/` - Python libraries for programmatic multi-screen automation.

## Virtual Screen Library

**Path:** `~/.claude/skills/use-computer/resources/virtual_screen/`

Spin up isolated Xvfb displays. Run N in parallel, no conflicts.

```python
import sys
sys.path.insert(0, "~/.claude/skills/use-computer/resources")
from virtual_screen import Screen

with Screen() as s:              # Auto display :100+
    s.launch("firefox")          # Any GUI app
    img = s.screenshot()         # PIL Image
    s.click(500, 300)
    s.type("hello")
    s.key("Return")
# Auto cleanup

# Parallel - just make more
screens = [Screen() for _ in range(10)]
```

## Selfbot System (Onion Architecture)

**Path:** `~/.claude/skills/use-computer/resources/selfbot/`

Scheduled GUI automation with proper layering:
- `domain/` - Pure models (Selfbot, Schedule, Execution)
- `application/` - Use cases (Runner, Manager)
- `infrastructure/` - Adapters (Screen, Storage, Scheduler)
- `factory.py` - Wires it all together
- `cli.py` - Command line interface

```python
from selfbot import SelfbotSystem, Schedule

system = SelfbotSystem()

# Create scheduled selfbot
bot = system.manager.create(
    name="etsy-checker",
    script_path="/path/to/check_etsy.py",
    schedule=Schedule(interval_seconds=3600),  # hourly
    output_file="/tmp/etsy_results.json"
)

# Run once
system.runner.run(bot)

# Or schedule
system.scheduler.add(bot)
system.scheduler.start()
```

**CLI:**
```bash
python -m selfbot.cli create etsy-checker ./script.py --interval 3600
python -m selfbot.cli run etsy-checker
python -m selfbot.cli list
python -m selfbot.cli daemon
```

## Selfbot Script Pattern

Your selfbot scripts receive env vars and should write output:

```python
#!/usr/bin/env python3
# /path/to/check_etsy.py
import os
import json

input_file = os.environ.get("SELFBOT_INPUT")
output_file = os.environ.get("SELFBOT_OUTPUT")

# Read input if provided
if input_file:
    data = json.load(open(input_file))

# Do automation work...
# (script runs inside a virtual screen)

# Write results
if output_file:
    json.dump({"status": "done", "results": [...]}, open(output_file, "w"))
```

---
## Skill Contents

- `resources/` (0 files: )
- `scripts/` (1 scripts: computer.sh)
