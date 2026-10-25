from __future__ import annotations

from garmin_to_wanderer import __version__


def test_version_is_available():
    assert isinstance(__version__, str)
    assert __version__
