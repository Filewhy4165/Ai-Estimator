from desktop.app import _THEME_PRESET_OPTIONS, resolve_theme_palette


def test_clearpath_theme_is_available_in_desktop_theme_options():
    assert "clearpath_teal" in _THEME_PRESET_OPTIONS


def test_clearpath_theme_uses_clearpath_style_dark_palette():
    palette = resolve_theme_palette("clearpath_teal", dark_mode=True)

    assert palette["app_bg"] == "#071012"
    assert palette["surface"] == "#0F1D21"
    assert palette["surface_2"] == "#13252A"
    assert palette["text"] == "#EFFDFA"
    assert palette["cyan"] == "#38E8FF"
    assert palette["lime"] == "#A8FF5A"
    assert palette["amber"] == "#FFC857"
    assert palette["danger"] == "#FF4F61"


def test_theme_palette_falls_back_to_default_for_unknown_preset():
    palette = resolve_theme_palette("not-a-real-theme", dark_mode=True)

    assert palette["app_bg"] == "#05070D"
    assert palette["cyan"] == "#19E6FF"
    assert palette["orange"] == "#FF5A1F"
