"""Windows installs include the IANA data required by the default timezone."""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement


def test_windows_runtime_dependencies_include_iana_timezone_data() -> None:
    project = Path(__file__).resolve().parents[1] / "pyproject.toml"
    metadata = tomllib.loads(project.read_text(encoding="utf-8"))
    requirements = [Requirement(value) for value in metadata["project"]["dependencies"]]
    windows = {
        requirement.name
        for requirement in requirements
        if requirement.marker is None
        or requirement.marker.evaluate({"platform_system": "Windows"})
    }
    assert "tzdata" in windows, (
        "A Windows runtime install must provide IANA timezone data"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installation contract")
def test_installed_windows_runtime_resolves_moscow_without_system_tzpath() -> None:
    # Isolate ZoneInfo's cache and clear system data paths to emulate a normal
    # Windows venv, rather than relying on this Conda host's bundled zone files.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from datetime import datetime, timedelta; "
                "from zoneinfo import ZoneInfo, reset_tzpath; "
                "reset_tzpath([]); "
                "assert datetime(2026, 9, 24, tzinfo=ZoneInfo('Europe/Moscow')).utcoffset() "
                "== timedelta(hours=3)"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
