"""手动 pip 清单由直播 JSON 锁生成，校验模式不写文件。"""
import json
from pathlib import Path

import pytest

from scripts.sync_live_requirements import main, sync


ROOT = Path(__file__).resolve().parents[2]
EXPECTED = "fixture-package==1.2.3 --hash=sha256:" + "a" * 64 + "\n"


@pytest.fixture
def source(tmp_path):
    lock = tmp_path / "resource/dependencies/live-python.lock.json"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({
        "packages": [{"name": "fixture-package", "version": "1.2.3", "sha256": "a" * 64}],
        "assets": [{"path": "ndgr_client/proto/fixture.py", "sha256": "b" * 64}],
    }), encoding="utf-8")
    return tmp_path


def test_repository_requirements_match_authoritative_lock():
    assert sync(ROOT, check=True)


def test_generation_keeps_manual_pip_syntax_and_excludes_protocol_assets(source):
    assert sync(source)
    assert (source / "requirements-live.txt").read_text(encoding="utf-8") == EXPECTED
    assert sync(source, check=True)


def test_check_reports_drift_without_rewriting_then_generation_repairs_it(source):
    requirements = source / "requirements-live.txt"
    requirements.write_text("old-package==0\n", encoding="utf-8")
    assert not sync(source, check=True)
    assert requirements.read_text(encoding="utf-8") == "old-package==0\n"
    assert sync(source)
    assert requirements.read_text(encoding="utf-8") == EXPECTED


def test_missing_check_does_not_create_requirements_and_cli_returns_failure(source, capsys):
    assert main(["--check"], root=source) == 1
    assert not (source / "requirements-live.txt").exists()
    assert "sync_live_requirements.py" in capsys.readouterr().err
    assert main([], root=source) == 0
    assert main(["--check"], root=source) == 0


@pytest.mark.parametrize("field, value", [("name", "package --extra-index-url=unsafe"),
                                         ("version", "1.0\nother-package"), ("sha256", "untrusted")])
def test_invalid_pins_are_not_published_as_manual_requirements(source, field, value):
    lock = source / "resource/dependencies/live-python.lock.json"
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["packages"][0][field] = value
    lock.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        sync(source)
    assert not (source / "requirements-live.txt").exists()
