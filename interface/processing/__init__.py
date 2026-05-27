"""
Processing module for pitch detection integration.

Integrates the pitch_estimate.py module with live camera frames.
"""

from .pipeline import PitchDetectionPipeline

__all__ = ['PitchDetectionPipeline']
