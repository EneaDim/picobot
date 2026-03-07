from pathlib import Path

import pytest

from picobot.config.schema import Config


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def cfg(tmp_workspace: Path) -> Config:
    return Config(workspace=str(tmp_workspace))
