from pathlib import Path

import pytest

from connector_forge.scenario import load

FILES = sorted((Path(__file__).resolve().parent.parent / "scenarios").rglob("*.yaml"))


def test_dev_set_size():
    assert len([f for f in FILES if f.parent.name == "dev"]) >= 16


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_scenario_file_loads(path):
    s = load(path)
    assert s.name == path.stem and s.description
