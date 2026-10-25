"""Synchronise Garmin Connect activities to Wanderer."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("garmin-to-wanderer")
except PackageNotFoundError:
    __version__ = "0.0.0"
