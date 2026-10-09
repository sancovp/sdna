"""
Virtual Screen Library - Universal GUI Automation

Spin up isolated Xvfb displays, run any GUI app, control programmatically.
Each screen is fully isolated - run N in parallel with no conflicts.

Usage:
    from virtual_screen import Screen

    s = Screen()                      # Auto-assigns display :100+
    s.launch("firefox")               # Launch any GUI app
    img = s.screenshot()              # PIL Image
    s.click(500, 300)                 # Click at coordinates
    s.type("hello")                   # Type text
    s.key("Return")                   # Press key
    s.close()                         # Cleanup
"""

import subprocess
import time
import os
import signal
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image
import tempfile


class Screen:
    """Isolated virtual screen for GUI automation."""

    _next_display = 100  # Start at :100 to avoid conflicts with :99

    def __init__(
        self,
        display: Optional[int] = None,
        size: Tuple[int, int] = (1920, 1080),
        depth: int = 24
    ):
        """
        Create a new virtual screen.

        Args:
            display: Display number (auto-assigned if None)
            size: Screen resolution (width, height)
            depth: Color depth (default 24-bit)
        """
        self.display_num = display if display is not None else self._get_next_display()
        self.display = f":{self.display_num}"
        self.size = size
        self.depth = depth
        self.env = os.environ.copy()
        self.env["DISPLAY"] = self.display

        self._xvfb_proc: Optional[subprocess.Popen] = None
        self._app_procs: list[subprocess.Popen] = []

        self._start_xvfb()

    @classmethod
    def _get_next_display(cls) -> int:
        """Get next available display number."""
        num = cls._next_display
        cls._next_display += 1
        return num

    def _start_xvfb(self):
        """Start the Xvfb virtual framebuffer."""
        screen_spec = f"{self.size[0]}x{self.size[1]}x{self.depth}"
        cmd = ["Xvfb", self.display, "-screen", "0", screen_spec]

        self._xvfb_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Wait for Xvfb to be ready
        time.sleep(0.5)

        if self._xvfb_proc.poll() is not None:
            raise RuntimeError(f"Failed to start Xvfb on {self.display}")

    def launch(self, command: str, wait: float = 1.0) -> subprocess.Popen:
        """
        Launch a GUI application on this screen.

        Args:
            command: Command to run (e.g., "firefox", "/path/to/app")
            wait: Seconds to wait for app to initialize

        Returns:
            The subprocess.Popen object for the launched app
        """
        proc = subprocess.Popen(
            command,
            shell=True,
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        self._app_procs.append(proc)
        time.sleep(wait)
        return proc

    def screenshot(self, path: Optional[str] = None) -> Image.Image:
        """
        Take a screenshot of the virtual screen.

        Args:
            path: Optional path to save the screenshot

        Returns:
            PIL Image object
        """
        if path is None:
            fd, path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            cleanup = True
        else:
            cleanup = False

        # Use ImageMagick import for reliability with compositors
        subprocess.run(
            ["import", "-window", "root", path],
            env=self.env,
            check=True,
            capture_output=True
        )

        img = Image.open(path)
        img.load()  # Force load before potential cleanup

        if cleanup:
            os.unlink(path)

        return img

    def click(self, x: int, y: int, button: int = 1):
        """
        Click at coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            button: Mouse button (1=left, 2=middle, 3=right)
        """
        subprocess.run(
            ["xdotool", "mousemove", str(x), str(y), "click", str(button)],
            env=self.env,
            check=True
        )

    def double_click(self, x: int, y: int):
        """Double-click at coordinates."""
        subprocess.run(
            ["xdotool", "mousemove", str(x), str(y),
             "click", "--repeat", "2", "--delay", "100", "1"],
            env=self.env,
            check=True
        )

    def right_click(self, x: int, y: int):
        """Right-click at coordinates."""
        self.click(x, y, button=3)

    def move(self, x: int, y: int):
        """Move mouse to coordinates."""
        subprocess.run(
            ["xdotool", "mousemove", str(x), str(y)],
            env=self.env,
            check=True
        )

    def type(self, text: str, delay_ms: int = 12):
        """
        Type text.

        Args:
            text: Text to type
            delay_ms: Delay between keystrokes in milliseconds
        """
        subprocess.run(
            ["xdotool", "type", "--delay", str(delay_ms), "--", text],
            env=self.env,
            check=True
        )

    def key(self, key: str):
        """
        Press a key or key combination.

        Args:
            key: Key name (e.g., "Return", "ctrl+c", "alt+Tab")
        """
        subprocess.run(
            ["xdotool", "key", "--", key],
            env=self.env,
            check=True
        )

    def drag(self, x1: int, y1: int, x2: int, y2: int):
        """
        Drag from one point to another.

        Args:
            x1, y1: Start coordinates
            x2, y2: End coordinates
        """
        subprocess.run(
            ["xdotool", "mousemove", str(x1), str(y1),
             "mousedown", "1",
             "mousemove", str(x2), str(y2),
             "mouseup", "1"],
            env=self.env,
            check=True
        )

    def get_mouse_position(self) -> Tuple[int, int]:
        """Get current mouse position."""
        result = subprocess.run(
            ["xdotool", "getmouselocation", "--shell"],
            env=self.env,
            capture_output=True,
            text=True,
            check=True
        )
        # Parse "X=123\nY=456\n..."
        pos = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                pos[k] = int(v)
        return pos.get("X", 0), pos.get("Y", 0)

    def get_active_window(self) -> str:
        """Get the name of the active window."""
        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            env=self.env,
            capture_output=True,
            text=True
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def focus_window(self, name: str):
        """Focus a window by name."""
        subprocess.run(
            ["xdotool", "search", "--name", name, "windowactivate"],
            env=self.env,
            check=True
        )

    def wait(self, seconds: float):
        """Wait for specified seconds."""
        time.sleep(seconds)

    def run_command(self, command: str) -> subprocess.CompletedProcess:
        """
        Run a shell command in the screen's environment.

        Args:
            command: Shell command to run

        Returns:
            CompletedProcess with stdout/stderr
        """
        return subprocess.run(
            command,
            shell=True,
            env=self.env,
            capture_output=True,
            text=True
        )

    def close(self):
        """Clean up all processes and the virtual display."""
        # Kill app processes
        for proc in self._app_procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()

        # Kill Xvfb
        if self._xvfb_proc and self._xvfb_proc.poll() is None:
            self._xvfb_proc.terminate()
            try:
                self._xvfb_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._xvfb_proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __repr__(self):
        return f"Screen(display={self.display}, size={self.size})"


# Convenience function for quick scripting
def quick_screen(**kwargs) -> Screen:
    """Create a screen with sensible defaults for quick scripting."""
    return Screen(**kwargs)
