"""Recording engine adapters. Lifecycle and integrity are owned by LiveRunner."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EngineFeatures:
    managed_outputs: bool = False
    per_file_tracks: bool = False
    annotate_report: bool = False
    original_working_directory: bool = False
    concatenate: bool = True
    clock_source: bool = False
    native_waiting: bool = False
    media_watchdog: bool = True
