"""
Run the pitch-control HIL harness without pytest.

This injects dummy pitch measurements through the same backend path used by
the tests:

    PitchMeasurement -> process_pitch_result() -> AppState.gui_set_feed_speed()

It uses mock SPI transports so it is safe to run on a Mac. The printed SPI
packets show what would be sent to the feed motor.
"""

from __future__ import annotations

import argparse
from typing import Sequence

from app_state import AppState
from comms.motor_spi import CommandPrefix, MockSPITransport, MotorController
from config import AppConfig
from pitch_control import PitchMeasurement, process_pitch_result


def _parse_csv_floats(raw: str) -> list[float]:
    """Parse command-line input like '5,6,7' into [5.0, 6.0, 7.0]."""
    try:
        return [float(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _parse_csv_strings(raw: str) -> list[str]:
    """Parse command-line input like 'HIGH,LOW,HIGH' into a list of strings."""
    return [item.strip() for item in raw.split(",") if item.strip()]


def make_hil_state(config: AppConfig) -> tuple[AppState, MockSPITransport, MockSPITransport]:
    """
    Build a fake AppState with mock motor transports.

    This is the key HIL setup.

    In the real machine:
        AppState -> MotorController -> real SPI transport -> motor controller board

    In this test:
        AppState -> MotorController -> MockSPITransport -> in-memory packet list

    So the backend still goes through the real AppState and MotorController logic,
    but packets are recorded instead of being physically sent.
    """

    # Separate fake SPI channels for wrapper and feed motors.
    # This lets us verify that automatic correction only sends commands
    # to the feed motor, not the wrapper motor.
    wrap_transport = MockSPITransport()
    feed_transport = MockSPITransport()

    # MotorController is still real here.
    # The only fake part is the SPI transport underneath it.
    wrap_controller = MotorController(wrap_transport)
    feed_controller = MotorController(feed_transport)

    # Mark mock controllers as open, similar to preparing real SPI hardware.
    wrap_controller.open()
    feed_controller.open()

    # AppState receives both controllers, just like the real app would.
    state = AppState(
        config,
        wrap_motor=wrap_controller,
        feed_motor=feed_controller,
    )

    return state, wrap_transport, feed_transport


def set_speed_packets(transport: MockSPITransport) -> list[bytes]:
    """
    Extract only SET_SPEED packets from a mock transport.

    MockSPITransport stores every packet in transport.sent.
    This helper filters out START/STOP/etc. and keeps only speed-change commands.
    """
    return [
        packet
        for packet in transport.sent
        if packet and packet[0] == CommandPrefix.SET_SPEED
    ]


def run_hil_pitch_sequence(
    pitches_mm: Sequence[float],
    confidences: Sequence[str],
    app_state: AppState,
    config: AppConfig,
    num_wraps: int = 10,
    telemetry=None,
    correction_gain: float = 1.0,
) -> list[str]:
    """
    Inject dummy pitch measurements through the real pitch-control backend.

    This is the core HIL loop.

    Each dummy pitch value is treated as if it came from the computer-vision
    pitch estimator. For example, pitch_mm = 5.0 means:

        "The camera measured the pitch as 5.0 mm."

    The backend then decides:
    - Is confidence LOW/FAILED? -> switch to Manual Mode, no correction.
    - Is machine OFF? -> no correction.
    - Is mode MANUAL? -> no correction.
    - Is pitch valid and confidence good? -> calculate new feed speed.

    The important part:
        process_pitch_result(...) is the same function used by the real
        AUTO camera path. So this is not a separate fake control algorithm.
    """

    logs = []

    for pitch_mm, confidence in zip(pitches_mm, confidences):

        # Create the minimal pitch result object consumed by the backend.
        # This replaces the real camera PitchResult during HIL testing.
        measurement = PitchMeasurement(
            measured_pitch_mm=pitch_mm,
            confidence=confidence,
            num_wraps=num_wraps,
            source="HIL",
        )

        # This is the real shared backend call.
        # It may call app_state.gui_set_feed_speed(new_speed),
        # which then sends a SET_SPEED packet through the feed motor controller.
        log = process_pitch_result(
            measurement,
            app_state,
            config,
            telemetry=telemetry,
            correction_gain=correction_gain,
        )

        print(log)
        logs.append(log)

    return logs


def _format_packet(packet: bytes) -> str:
    """Format raw SPI bytes as readable hex, e.g. b'\\x03\\x0c\\x00' -> '03 0C 00'."""
    return packet.hex(" ").upper()


def _expand_confidences(confidences: Sequence[str], count: int) -> list[str]:
    """
    Allow either:
    - one confidence value reused for every pitch, e.g. HIGH
    - one confidence per pitch, e.g. HIGH,HIGH,LOW

    This keeps command-line testing quick.
    """
    if len(confidences) == count:
        return list(confidences)

    if len(confidences) == 1:
        return [confidences[0]] * count

    raise SystemExit(
        "Number of confidences must be 1 or match the number of pitch values."
    )


def build_parser() -> argparse.ArgumentParser:
    """
    Define command-line inputs.

    Example:
        python3 hil_test.py --target-mm 6 --feed-mm-s 10 --pitches-mm 5,6,7

    Default behaviour:
        target pitch = 6 mm
        initial feed = 10 mm/s
        injected pitch sequence = 5, 6, 7 mm
        confidence = HIGH for all readings
    """
    parser = argparse.ArgumentParser(
        description="Inject pitch measurements through the pitch-control backend.",
    )

    parser.add_argument(
        "--target-mm",
        type=float,
        default=6.0,
        help="Target pitch in mm. Default: 6.0",
    )

    parser.add_argument(
        "--feed-mm-s",
        type=float,
        default=10.0,
        help="Initial feed speed in mm/s. Default: 10.0",
    )

    parser.add_argument(
        "--pitches-mm",
        type=_parse_csv_floats,
        default=[5.0, 6.0, 7.0],
        help="Comma-separated measured pitches in mm. Default: 5,6,7",
    )

    parser.add_argument(
        "--confidences",
        type=_parse_csv_strings,
        default=["HIGH"],
        help=(
            "Comma-separated confidences. Provide one value to reuse for every"
            " pitch, or one per pitch. Default: HIGH"
        ),
    )

    parser.add_argument(
        "--num-wraps",
        type=int,
        default=10,
        help="Detected wrap count attached to each injected measurement. Default: 10",
    )

    return parser


def main() -> int:
    """
    Run the HIL command-line test.

    The final printed output shows:
    - final mode: AUTO or MANUAL
    - final feed speed stored in AppState
    - feed SET_SPEED packets that would have been sent to Group B
    - wrapper SET_SPEED packets, which should remain zero for AUTO pitch correction
    """

    args = build_parser().parse_args()

    pitches_mm = args.pitches_mm
    confidences = _expand_confidences(args.confidences, len(pitches_mm))

    # AppConfig stores target pitch in micrometres, so convert mm -> µm.
    config = AppConfig(target_pitch_um=args.target_mm * 1000.0)

    # Create fake AppState + mock wrap/feed SPI channels.
    state, wrap_transport, feed_transport = make_hil_state(config)

    print("Pitch-control HIL harness")
    print(f"  target pitch : {args.target_mm:.3f} mm")
    print(f"  initial feed : {args.feed_mm_s:.3f} mm/s")
    print(f"  pitches      : {', '.join(f'{p:.3f}' for p in pitches_mm)} mm")
    print(f"  confidences  : {', '.join(confidences)}")
    print(f"  wraps        : {args.num_wraps}")
    print()

    # Turn the virtual machine on.
    # This causes START packets to be sent to the mock motor controllers.
    state.gui_set_machine_on(True)

    # Set initial feed speed.
    # This produces an initial SET_SPEED packet, but it is setup rather than
    # an automatic correction, so we clear it before running the HIL sequence.
    state.gui_set_feed_speed(args.feed_mm_s)

    # Clear setup packets so the final summary only shows correction packets.
    wrap_transport.sent.clear()
    feed_transport.sent.clear()

    # Inject dummy pitch values into the real backend.
    logs = run_hil_pitch_sequence(
        pitches_mm,
        confidences,
        state,
        config,
        num_wraps=args.num_wraps,
    )

    # Pull out only speed-change packets from each fake motor channel.
    feed_packets = set_speed_packets(feed_transport)
    wrap_packets = set_speed_packets(wrap_transport)

    print()
    print("Summary")

    # This tells us whether LOW/FAILED confidence forced Manual Mode.
    print(f"  final mode       : {state.mode.value.upper()}")

    # This is the final feed speed stored in AppState after all corrections.
    print(f"  final feed speed : {state.feed_speed_mms:.3f} mm/s")

    # These are the feed motor commands that would have gone to Group B.
    print(f"  feed SET_SPEED   : {len(feed_packets)} packet(s)")
    for packet in feed_packets:
        print(f"    {_format_packet(packet)}")

    # This should stay zero for automatic pitch correction, because the
    # wrapper motor speed is fixed in our control strategy.
    print(f"  wrap SET_SPEED   : {len(wrap_packets)} packet(s)")
    if not wrap_packets:
        print("    none")

    # Return 0 if the sequence ran and produced logs.
    return 0 if logs else 1


if __name__ == "__main__":
    raise SystemExit(main())