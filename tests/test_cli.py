import json

import pytest

from app.cli import main
from tests.conftest import StaticProvider


def test_cli(monkeypatch, features, tmp_path, capsys):
    monkeypatch.setattr(
        "sys.argv",
        [
            "geoforge",
            "--lat",
            "44.6",
            "--lon",
            "33.5",
            "--radius",
            "500",
            "--output-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(
        "app.services.generation.OSMProvider", lambda: StaticProvider(features)
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["buildings"] == 1


@pytest.mark.parametrize(
    "args", [[], ["--lat", "44.6"], ["--bbox", "33", "44", "34", "45", "--lat", "44"]]
)
def test_cli_arguments(monkeypatch, args):
    monkeypatch.setattr("sys.argv", ["geoforge", *args])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
