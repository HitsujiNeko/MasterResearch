"""summary.py（サマリーJSON保存）のテスト。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.common import summary as summary_module
from src.common.summary import (
    CODE_WATCH_PATHS,
    build_provenance,
    compute_code_sha256,
    compute_file_sha256,
    describe_code_files,
    describe_input_files,
    get_git_state,
    get_package_versions,
    save_summary,
    script_module_to_path,
)


def _git(repo: Path, *args: str) -> None:
    """一時リポジトリで git を実行する（実行者のグローバル設定の影響を切り離す）。"""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def _commit_all(repo: Path) -> None:
    """作業ツリーの内容をすべてコミットする（コミット署名は無効にする）。"""
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "init",
    )


def _require_git() -> None:
    """git が無い環境では実リポジトリを使うテストを飛ばす。"""
    if shutil.which("git") is None:
        pytest.skip("git が利用できない環境")


def test_save_summary_round_trip(tmp_path: Path) -> None:
    """保存した内容を再読込すると元の辞書と一致する。"""
    summary_path = tmp_path / "summary.json"
    summary = {"count": 3, "note": "テスト"}

    save_summary(summary, summary_path)

    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary


def test_save_summary_does_not_escape_japanese(tmp_path: Path) -> None:
    """日本語が\\uXXXXへエスケープされずそのまま保存される。"""
    summary_path = tmp_path / "summary.json"
    save_summary({"note": "ハノイ"}, summary_path)

    text = summary_path.read_text(encoding="utf-8")
    assert "ハノイ" in text
    assert "\\u" not in text


def test_save_summary_creates_parent_directory(tmp_path: Path) -> None:
    """親ディレクトリが存在しない場合は自動作成する。"""
    summary_path = tmp_path / "nested" / "dir" / "summary.json"

    save_summary({"ok": True}, summary_path)

    assert summary_path.exists()


def test_save_summary_rejects_nan(tmp_path: Path) -> None:
    """NaNはJSON標準に無いため、気づかず保存されないよう例外にする。"""
    summary_path = tmp_path / "summary.json"

    with pytest.raises(ValueError, match="NaN"):
        save_summary({"pearson_r": math.nan}, summary_path)


def test_save_summary_rejects_infinity(tmp_path: Path) -> None:
    """Infinityも同様に弾く（ゼロ除算の見落とし対策）。"""
    summary_path = tmp_path / "summary.json"

    with pytest.raises(ValueError, match="NaN"):
        save_summary({"ratio": math.inf}, summary_path)


def test_save_summary_does_not_write_file_when_rejected(tmp_path: Path) -> None:
    """NaN検出時は書き出さず、壊れた内容のファイルを残さない。"""
    summary_path = tmp_path / "summary.json"

    with pytest.raises(ValueError):
        save_summary({"value": math.nan}, summary_path)

    assert not summary_path.exists()


def test_compute_file_sha256_matches_hashlib(tmp_path: Path) -> None:
    """チャンク読み込みでも hashlib による一括計算と同じハッシュになる。"""
    target = tmp_path / "input.bin"
    content = b"hanoi" * 500_000  # 読み込み単位（1MiB）を跨ぐサイズ
    target.write_bytes(content)

    assert compute_file_sha256(target) == hashlib.sha256(content).hexdigest()


def test_compute_file_sha256_missing_file_raises(tmp_path: Path) -> None:
    """存在しないファイルは FileNotFoundError になる。"""
    with pytest.raises(FileNotFoundError, match="見つかりません"):
        compute_file_sha256(tmp_path / "missing.gpkg")


def test_get_package_versions_marks_missing_package_as_none() -> None:
    """インストール済みは版文字列、未インストールは None になる。"""
    versions = get_package_versions(["pytest", "no-such-package-for-provenance-test"])

    assert isinstance(versions["pytest"], str)
    assert versions["no-such-package-for-provenance-test"] is None


@pytest.mark.parametrize(("status", "expected_dirty"), [("", False), (" M src/a.py", True)])
def test_get_git_state_judges_dirty_from_status(
    monkeypatch: pytest.MonkeyPatch, status: str, expected_dirty: bool
) -> None:
    """src 配下の status 出力の有無で dirty を判定する。"""
    calls: list[list[str]] = []

    def fake_run_git(args: list[str], repo_root: Path) -> str:
        calls.append(args)
        return "a" * 40 if args[0] == "rev-parse" else status

    monkeypatch.setattr(summary_module, "_run_git", fake_run_git)

    assert get_git_state() == {"commit": "a" * 40, "dirty": expected_dirty}
    # 判定対象はコード（src 配下）に限定されている
    assert calls[1] == ["status", "--porcelain", "--untracked-files=normal", "--", "src"]


def test_get_git_state_returns_none_when_git_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """git の実行に失敗した場合は例外にせず None を記録する。"""
    monkeypatch.setattr(summary_module, "_run_git", lambda args, repo_root: None)

    assert get_git_state() == {"commit": None, "dirty": None}


def test_get_git_state_ignores_changes_outside_src(tmp_path: Path) -> None:
    """実際の git リポジトリで、src 外の変更・未追跡ファイルは dirty にしない。"""
    _require_git()
    _git(tmp_path, "init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "code.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "result.json").write_text("{}\n", encoding="utf-8")
    _commit_all(tmp_path)

    # 結果ファイルの更新と src 外の未追跡ファイルでは dirty にならない
    (tmp_path / "result.json").write_text('{"a": 1}\n', encoding="utf-8")
    (tmp_path / "scratch.txt").write_text("tmp\n", encoding="utf-8")
    state = get_git_state(tmp_path)
    assert len(state["commit"]) == 40
    assert state["dirty"] is False

    # src 配下の未追跡ファイルでは dirty になる
    new_code = tmp_path / "src" / "new.py"
    new_code.write_text("y = 1\n", encoding="utf-8")
    assert get_git_state(tmp_path)["dirty"] is True
    new_code.unlink()

    # コードの変更では dirty になる
    (tmp_path / "src" / "code.py").write_text("x = 2\n", encoding="utf-8")
    assert get_git_state(tmp_path)["dirty"] is True


def test_compute_code_sha256_ignores_crlf_difference() -> None:
    """CRLF と LF の違いだけならハッシュは一致し、LF の内容の SHA-256 になる。"""
    lf_content = b"x = 1\ny = 2\n"

    assert compute_code_sha256(b"x = 1\r\ny = 2\r\n") == compute_code_sha256(lf_content)
    assert compute_code_sha256(lf_content) == hashlib.sha256(lf_content).hexdigest()
    # 改行以外の内容の違いは別のハッシュになる
    assert compute_code_sha256(b"x = 2\n") != compute_code_sha256(b"x = 1\n")


def test_script_module_to_path() -> None:
    """モジュール名をリポジトリ相対の .py のパスに変換する。"""
    assert (
        script_module_to_path("src.analysis.analysis_rq3_limited")
        == "src/analysis/analysis_rq3_limited.py"
    )


def test_describe_code_files_lists_tracked_files_under_watch_paths(tmp_path: Path) -> None:
    """監視パス配下の追跡ファイルだけを、パス順に LF にそろえたハッシュで記録する。"""
    _require_git()
    _git(tmp_path, "init", "-q")
    (tmp_path / "src" / "common").mkdir(parents=True)
    (tmp_path / "src" / "common" / "b.py").write_bytes(b"b = 1\r\n")
    (tmp_path / "src" / "common" / "a.py").write_bytes(b"a = 1\n")
    (tmp_path / "src" / "common" / "gone.py").write_bytes(b"gone = 1\n")
    (tmp_path / "src" / "script.py").write_bytes(b"run()\n")
    (tmp_path / "src" / "other.py").write_bytes(b"other = 1\n")
    _commit_all(tmp_path)

    # 未追跡のファイルと、作業ツリーから削除した追跡ファイルは含めない
    (tmp_path / "src" / "common" / "untracked.py").write_bytes(b"u = 1\n")
    (tmp_path / "src" / "common" / "gone.py").unlink()

    code = describe_code_files(["src/script.py", "src/common"], tmp_path)

    assert code == {
        "watch_paths": ["src/script.py", "src/common"],
        "files": [
            {"path": "src/common/a.py", "sha256": hashlib.sha256(b"a = 1\n").hexdigest()},
            {"path": "src/common/b.py", "sha256": hashlib.sha256(b"b = 1\n").hexdigest()},
            {"path": "src/script.py", "sha256": hashlib.sha256(b"run()\n").hexdigest()},
        ],
    }


def test_describe_code_files_returns_none_when_git_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """git の実行に失敗した場合は例外にせず None を返す。"""
    monkeypatch.setattr(summary_module, "_run_git", lambda args, repo_root: None)

    assert describe_code_files(["src/common"]) is None


def test_describe_input_files_uses_project_relative_path(tmp_path: Path) -> None:
    """入力パスは基準ディレクトリからの相対パス（/ 区切り）で記録される。"""
    target = tmp_path / "data" / "input.csv"
    target.parent.mkdir()
    # write_text は Windows で改行を CRLF に変換し期待ハッシュとずれるため、バイト列で書く
    content = b"a,b\n1,2\n"
    target.write_bytes(content)

    described = describe_input_files([target], project_root=tmp_path)

    assert described == [{"path": "data/input.csv", "sha256": hashlib.sha256(content).hexdigest()}]


def test_build_provenance_schema_and_json_serializable(tmp_path: Path) -> None:
    """来歴は所定のキーを持ち、save_summary でそのまま保存できる。"""
    target = tmp_path / "input.csv"
    target.write_text("x\n", encoding="utf-8")
    executed_at = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)

    provenance = build_provenance(
        "src.analysis.example",
        input_paths=[target],
        packages=["pytest"],
        repo_root=tmp_path,
        executed_at=executed_at,
    )

    assert set(provenance) == {
        "script",
        "executed_at",
        "python_version",
        "platform",
        "git",
        "code",
        "packages",
        "inputs",
    }
    assert provenance["script"] == "src.analysis.example"
    assert provenance["executed_at"] == "2026-09-26T12:00:00+00:00"
    assert provenance["inputs"][0]["path"] == "input.csv"
    assert list(provenance["packages"]) == ["pytest"]

    # 既存のサマリーへ provenance キーとして追加して保存できる
    summary_path = tmp_path / "summary.json"
    save_summary({"count": 1, "provenance": provenance}, summary_path)
    saved = json.loads(summary_path.read_text(encoding="utf-8"))
    assert saved["provenance"] == provenance


def test_build_provenance_records_code_of_script_and_watch_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """コードのハッシュは生成スクリプトと既定の監視パスを範囲として記録する。"""
    calls: list[list[str]] = []

    def fake_describe_code_files(watch_paths: list[str], repo_root: Path) -> dict[str, object]:
        calls.append(list(watch_paths))
        return {"watch_paths": list(watch_paths), "files": []}

    monkeypatch.setattr(summary_module, "describe_code_files", fake_describe_code_files)

    provenance = build_provenance("src.analysis.example", packages=[], repo_root=tmp_path)

    assert calls == [["src/analysis/example.py", *CODE_WATCH_PATHS]]
    assert provenance["code"] == {"watch_paths": calls[0], "files": []}


def test_build_provenance_rejects_naive_datetime(tmp_path: Path) -> None:
    """タイムゾーン無しの日時は ValueError になる。"""
    with pytest.raises(ValueError, match="タイムゾーン"):
        build_provenance("x", repo_root=tmp_path, executed_at=datetime(2026, 9, 26, 12, 0))


def test_build_provenance_converts_executed_at_to_utc(tmp_path: Path) -> None:
    """タイムゾーン付きの日時は UTC に変換して記録する。"""
    jst = timezone(timedelta(hours=9))
    provenance = build_provenance(
        "x", packages=[], repo_root=tmp_path, executed_at=datetime(2026, 9, 26, 21, 0, tzinfo=jst)
    )

    assert provenance["executed_at"] == "2026-09-26T12:00:00+00:00"
