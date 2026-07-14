from __future__ import annotations

from textual.message import Message
from textual.widget import Widget

BAR_WIDTH = 8


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


class Slider(Widget, can_focus=True):
    DEFAULT_CSS = """
    Slider { height: 1; }
    Slider:focus { background: $accent 30%; }
    """

    class Changed(Message):
        def __init__(self, slider: "Slider", value: int) -> None:
            self.slider = slider
            self.value = value
            super().__init__()

    def __init__(self, label, minimum, maximum, value, step=1, key=None, fmt=str, id=None):
        super().__init__(id=id)
        self.label = label
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.key = key
        self.fmt = fmt
        self.value = self._clamped(value)

    def _clamped(self, value: int) -> int:
        return clamp(value, self.minimum, self.maximum)

    def adjust(self, delta: int) -> int:
        new = self._clamped(self.value + delta * self.step)
        if new != self.value:
            self.value = new
            self.refresh()
            self.post_message(self.Changed(self, new))
        return self.value

    def render(self):
        span = self.maximum - self.minimum
        filled = 0 if span == 0 else round((self.value - self.minimum) / span * BAR_WIDTH)
        bar = "═" * filled + "●" + "═" * (BAR_WIDTH - filled)
        return f"{self.label:16.16} {bar} {self.fmt(self.value)}"

    def on_key(self, event) -> None:
        if event.key == "left":
            self.adjust(-1)
            event.stop()
        elif event.key == "right":
            self.adjust(1)
            event.stop()
        elif event.key == "up":
            self.screen.focus_previous()
            event.stop()
        elif event.key == "down":
            self.screen.focus_next()
            event.stop()
