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


def test_in_range_set_emits_and_remembers(qapp):
    panel = MotorMetricPanel(
        "Wrapper Motor", 1000.0, speed_min=0.0, speed_max=3000.0, unit="RPM"
    )
    accepted, rejected = [], []
    panel.manual_speed_changed.connect(accepted.append)
    panel.manual_speed_rejected.connect(rejected.append)

    panel.manual_input.setText("1500")
    panel._on_set_clicked()

    assert accepted == [1500.0]
    assert rejected == []
    assert panel._last_valid_text == "1500"


def test_out_of_range_set_reverts_and_rejects(qapp):
    panel = MotorMetricPanel(
        "Wrapper Motor", 1000.0, speed_min=0.0, speed_max=3000.0, unit="RPM"
    )
    accepted, rejected = [], []
    panel.manual_speed_changed.connect(accepted.append)
    panel.manual_speed_rejected.connect(rejected.append)

    # Establish a previous within-range value.
    panel.manual_input.setText("1500")
    panel._on_set_clicked()

    # Now enter an out-of-range value and SET.
    panel.manual_input.setText("5000")
    panel._on_set_clicked()

    assert accepted == [1500.0]                  # second SET did NOT emit
    assert len(rejected) == 1
    assert panel.manual_input.text() == "1500"   # reverted to previous valid