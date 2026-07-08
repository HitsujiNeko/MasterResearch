"""gee.py（GEE認証・初期化）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.common import gee


def test_authenticate_gee_initialize_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initializeが成功すればAuthenticateは呼ばれない。"""
    authenticate_calls: list[bool] = []
    monkeypatch.setattr(gee.ee, "Initialize", lambda project: None)
    monkeypatch.setattr(gee.ee, "Authenticate", lambda: authenticate_calls.append(True))

    gee.authenticate_gee("dummy-project")

    assert authenticate_calls == []


def test_authenticate_gee_falls_back_to_authenticate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initialize失敗時はAuthenticate経由で再Initializeに成功する。"""
    initialize_calls = {"count": 0}

    def fake_initialize(project: str) -> None:
        initialize_calls["count"] += 1
        if initialize_calls["count"] == 1:
            raise RuntimeError("not authenticated")

    monkeypatch.setattr(gee.ee, "Initialize", fake_initialize)
    monkeypatch.setattr(gee.ee, "Authenticate", lambda: None)

    gee.authenticate_gee("dummy-project")

    assert initialize_calls["count"] == 2


def test_authenticate_gee_raises_when_both_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """InitializeもAuthenticate後の再Initializeも失敗した場合は例外を送出する。"""

    def fake_initialize(project: str) -> None:
        raise RuntimeError("initialize always fails")

    monkeypatch.setattr(gee.ee, "Initialize", fake_initialize)
    monkeypatch.setattr(gee.ee, "Authenticate", lambda: None)

    with pytest.raises(RuntimeError):
        gee.authenticate_gee("dummy-project")


def test_load_gee_project_id_explicit_takes_priority(tmp_path: Path) -> None:
    """明示指定があれば設定CSVを見ずにそれを返す。"""
    result = gee.load_gee_project_id(tmp_path / "missing.csv", explicit_project_id=" my-project ")

    assert result == "my-project"


def test_load_gee_project_id_from_config_csv(tmp_path: Path) -> None:
    """明示指定がなければ設定CSVのgee_project_id列から取得する。"""
    config_path = tmp_path / "gee_config.csv"
    pd.DataFrame({"gee_project_id": ["csv-project"]}).to_csv(config_path, index=False)

    result = gee.load_gee_project_id(config_path)

    assert result == "csv-project"


def test_load_gee_project_id_missing_config_raises(tmp_path: Path) -> None:
    """設定CSVが存在しない場合はFileNotFoundErrorになる。"""
    with pytest.raises(FileNotFoundError):
        gee.load_gee_project_id(tmp_path / "missing.csv")


def test_load_gee_project_id_rejects_placeholder(tmp_path: Path) -> None:
    """プレースホルダのままの場合はValueErrorになる。"""
    config_path = tmp_path / "gee_config.csv"
    pd.DataFrame({"gee_project_id": ["YOUR_GCP_PROJECT_ID"]}).to_csv(config_path, index=False)

    with pytest.raises(ValueError):
        gee.load_gee_project_id(config_path)
