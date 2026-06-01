"""
Processing module for pitch detection integration.

Integrates the pitch_estimate.py module with live camera frames.
"""

from .pipeline import PitchDetectionPipeline, PITCH_DETECTION_INTERVAL_MS

__all__ = ['PitchDetectionPipeline', 'PITCH_DETECTION_INTERVAL_MS']
