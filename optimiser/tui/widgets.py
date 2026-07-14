from __future__ import annotations

from textual.message import Message
from textual.widget import Widget
from textual.widgets import TabPane

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
        elif event.key in ("up", "down"):
            self._focus_sibling(1 if event.key == "down" else -1)
            event.stop()

    def _focus_sibling(self, delta: int) -> None:
        """Move focus to the previous/next Slider within the same tab, clamped
        at the ends so up/down stays inside the control group."""
        pane = next((a for a in self.ancestors if isinstance(a, TabPane)), None)
        scope = pane if pane is not None else self.screen
        sliders = list(scope.query(Slider))
        if self in sliders:
            j = sliders.index(self) + delta
            if 0 <= j < len(sliders):
                sliders[j].focus()
