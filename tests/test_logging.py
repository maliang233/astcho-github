from astcho.logging import preview


def test_log_preview_is_single_line_and_bounded():
    value = preview("第一行\n第二行 " + "很长" * 100, 20)
    assert "\n" not in value
    assert value.endswith("...")
    assert len(value) == 23
