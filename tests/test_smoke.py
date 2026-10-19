import connector_forge
from connector_forge.cli import main


def test_version():
    assert connector_forge.__version__


def test_cli_runs():
    assert main([]) == 0
