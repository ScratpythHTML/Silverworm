from ui.motor_panel import MotorMetricPanel


def test_motor_metric_panel_uses_feed_units(qapp):
    panel = MotorMetricPanel(
        "Feed Motor",
        1.0,
        speed_min=0.0,
        speed_max=10.0,
        unit="mm/s",
    )

    assert panel._target_label.text() == "1 mm/s"
    assert panel.actual_value.text() == "-- mm/s"
    assert panel.manual_input.placeholderText() == "0 – 10 mm/s"
    assert panel.manual_input.validator() is not None


def test_motor_metric_panel_uses_wrap_units(qapp):
    panel = MotorMetricPanel(
        "Wrapper Motor",
        1000.0,
        speed_min=0.0,
        speed_max=3000.0,
        unit="RPM",
    )

    assert panel._target_label.text() == "1000 RPM"
    assert panel.actual_value.text() == "-- RPM"
    assert panel.manual_input.placeholderText() == "0 – 3000 RPM"
    assert panel.manual_input.validator() is not None