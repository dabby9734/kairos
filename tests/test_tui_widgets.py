from kairos.tui.widgets import Slider, clamp


def test_clamp():
    assert clamp(3, 1, 5) == 3
    assert clamp(-2, 0, 10) == 0
    assert clamp(99, 0, 10) == 10


def test_slider_adjust_clamps_and_steps():
    s = Slider("free_days", 0, 10, 4, step=1, key="free_days")
    assert s.value == 4
    s.value = 9
    # adjust does not exceed maximum
    assert s._clamped(s.value + 5) == 10
    assert s._clamped(0 - 3) == 0


def test_slider_render_contains_label_and_value():
    s = Slider("gaps", 0, 10, 2, key="gaps")
    text = s.render()
    assert "gaps" in text and "2" in text
