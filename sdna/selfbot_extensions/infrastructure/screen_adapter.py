"""
Screen Adapter - Bridges domain to virtual_screen library.

Infrastructure layer: implements ScreenProvider protocol.
"""

from ..domain.models import ScreenProvider
from ..virtual_screen import Screen


class VirtualScreenProvider(ScreenProvider):
    """Provides virtual screens via the virtual_screen library."""

    def create_screen(self, size: tuple[int, int]) -> Screen:
        """Create an isolated Xvfb-backed virtual screen."""
        return Screen(size=size)
