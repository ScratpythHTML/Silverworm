#!/usr/bin/env python3
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
    try:
        return [float(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _parse_csv_strings(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def make_hil_state(config: AppConfig) -> tuple[AppState, MockSPITransport, MockSPITransport]:
    wrap_transport = MockSPITransport()
    feed_transport = MockSPITransport()
    wrap_controller = MotorController(wrap_transport)
    feed_controller = MotorController(feed_transport)

    wrap_controller.open()
    feed_controller.open()

    state = AppState(
        config,
        wrap_motor=wrap_controller,
        feed_motor=feed_controller,
    )
    return state, wrap_transport, feed_transport


def set_speed_packets(transport: MockSPITransport) -> list[bytes]:
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
    """Inject dummy measurements through the real control path.

    Pass a TelemetryLog to collect motor-response / pitch-sensitivity data —
    HIL uses the same telemetry structure as the live camera path.
    """
    logs = []
    for pitch_mm, confidence in zip(pitches_mm, confidences):
        measurement = PitchMeasurement(
            measured_pitch_mm=pitch_mm,
            confidence=confidence,
            num_wraps=num_wraps,
            source="HIL",
        )
        log = process_pitch_result(
            measurement, app_state, config,
            telemetry=telemetry, correction_gain=correction_gain,
        )
        print(log)
        logs.append(log)
    return logs


def _format_packet(packet: bytes) -> str:
    return packet.hex(" ").upper()


def _expand_confidences(confidences: Sequence[str], count: int) -> list[str]:
    if len(confidences) == count:
        return list(confidences)
    if len(confidences) == 1:
        return [confidences[0]] * count
    raise SystemExit(
        "Number of confidences must be 1 or match the number of pitch values."
    )


def build_parser() -> argparse.ArgumentParser:
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
    args = build_parser().parse_args()
    pitches_mm = args.pitches_mm
    confidences = _expand_confidences(args.confidences, len(pitches_mm))

    config = AppConfig(target_pitch_um=args.target_mm * 1000.0)
    state, wrap_transport, feed_transport = make_hil_state(config)

    print("Pitch-control HIL harness")
    print(f"  target pitch : {args.target_mm:.3f} mm")
    print(f"  initial feed : {args.feed_mm_s:.3f} mm/s")
    print(f"  pitches      : {', '.join(f'{p:.3f}' for p in pitches_mm)} mm")
    print(f"  confidences  : {', '.join(confidences)}")
    print(f"  wraps        : {args.num_wraps}")
    print()

    state.gui_set_machine_on(True)
    state.gui_set_feed_speed(args.feed_mm_s)
    wrap_transport.sent.clear()
    feed_transport.sent.clear()

    logs = run_hil_pitch_sequence(
        pitches_mm,
        confidences,
        state,
        config,
        num_wraps=args.num_wraps,
    )

    feed_packets = set_speed_packets(feed_transport)
    wrap_packets = set_speed_packets(wrap_transport)

    print()
    print("Summary")
    print(f"  final mode       : {state.mode.value.upper()}")
    print(f"  final feed speed : {state.feed_speed_mms:.3f} mm/s")
    print(f"  feed SET_SPEED   : {len(feed_packets)} packet(s)")
    for packet in feed_packets:
        print(f"    {_format_packet(packet)}")
    print(f"  wrap SET_SPEED   : {len(wrap_packets)} packet(s)")
    if not wrap_packets:
        print("    none")

    return 0 if logs else 1


if __name__ == "__main__":
    raise SystemExit(main())
