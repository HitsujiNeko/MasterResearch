"""scripts/check_result_staleness.py（分析結果の陳腐化検出）のテスト。

コードの差分判定は git の木の比較に依存するため、`tmp_path` に一時リポジトリを作り、
実際の git コマンドで検証する。実リポジトリの `data/output/` には触れない。
対象は ``src`` パッケージ外のスクリプトのため、``tests/scripts`` との import 名の衝突を
避けるよう、ファイルパスを指定して読み込む。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from src.common.summary import describe_code_files

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_result_staleness.py"


def _load_target() -> ModuleType:
    """対象スクリプトをモジュールとして読み込む。"""
    spec = importlib.util.spec_from_file_location("check_result_staleness", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


target = _load_target()

SCRIPT_MODULE = "src.analysis.run_model"
INPUT_REL = "data/output/datasets/dataset.gpkg"


def _git(repo: Path, *args: str) -> str:
    """一時リポジトリで git を実行し、標準出力を返す。"""
    completed = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _commit_all(repo: Path, message: str) -> str:
    """作業ツリーの変更をすべてコミットし、コミットハッシュを返す。"""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """生成スクリプト・共通モジュール・入力を持つ一時リポジトリ（初回コミット済み）。"""
    root = tmp_path / "repo"
    (root / "src" / "analysis").mkdir(parents=True)
    (root / "src" / "common").mkdir(parents=True)
    (root / "src" / "analysis" / "run_model.py").write_text("VERSION = 1\n", encoding="utf-8")
    (root / "src" / "analysis" / "other.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "common" / "util.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "analysis" / "urban_params").mkdir(parents=True)
    (root / "src" / "analysis" / "urban_params" / "canonical_grid.py").write_text(
        "BLOCK = 1\n", encoding="utf-8"
    )
    (root / "data" / "output" / "datasets").mkdir(parents=True)
    (root / INPUT_REL).write_bytes(b"dataset-v1")
    # 報告モードは main でのみ動くため、利用者の init.defaultBranch に依らず main にそろえる
    subprocess.run(["git", "init", "-q", "--initial-branch", "main"], cwd=root, check=True)
    _commit_all(root, "initial")
    return root


def _sha256(data: bytes) -> str:
    """バイト列の SHA-256 を返す。"""
    return hashlib.sha256(data).hexdigest()


def _provenance(
    commit: str | None,
    *,
    dirty: bool = False,
    inputs: list[dict[str, str]] | None = None,
    script: str | None = SCRIPT_MODULE,
) -> dict[str, object]:
    """結果 JSON に埋め込む来歴を作る。"""
    provenance: dict[str, object] = {
        "git": {"commit": commit, "dirty": dirty},
        "inputs": inputs if inputs is not None else [],
    }
    if script is not None:
        provenance["script"] = script
    return provenance


def _write_result(root: Path, name: str, content: object) -> Path:
    """結果 JSON を `data/output/analysis/` に書き出す。"""
    path = root / "data" / "output" / "analysis" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text, encoding="utf-8")
    return path


def _check(root: Path, path: Path, **kwargs: object) -> object:
    """結果ファイル1件を判定する（基準ディレクトリはすべて一時リポジトリ）。"""
    git = target.GitRepository(root)
    hash_cache = kwargs.pop("hash_cache", {})
    return target.check_result_file(path, root, root, git, hash_cache, **kwargs)


def _input_entry(sha256: str | None = None) -> dict[str, str]:
    """入力ファイルの来歴を作る（既定は現在の入力ファイルのハッシュ）。"""
    return {"path": INPUT_REL, "sha256": sha256 or _sha256(b"dataset-v1")}


# --- 5分類 ---


def test_up_to_date_when_inputs_and_code_unchanged(repo: Path) -> None:
    """入力・コードとも生成時から変わっていなければ最新と判定する。"""
    commit = _git(repo, "rev-parse", "HEAD")
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[_input_entry()])}
    )
    result = _check(repo, path)
    assert result.status == target.STATUS_UP_TO_DATE
    assert result.recorded_commit == commit
    assert result.changed_files == []


@pytest.mark.parametrize(
    "content",
    [{"sample_size": 10}, {"provenance": "text"}, "{not json", ["list"]],
    ids=["missing", "not_dict", "invalid_json", "not_object"],
)
def test_no_provenance(repo: Path, content: object) -> None:
    """来歴が無い・辞書でない・JSON を解釈できない場合は来歴なしと判定する。"""
    path = _write_result(repo, "a_results.json", content)
    result = _check(repo, path)
    assert result.status == target.STATUS_NO_PROVENANCE
    assert result.reasons[target.STATUS_NO_PROVENANCE]


def test_input_missing(repo: Path) -> None:
    """記録された入力ファイルが無ければ入力欠落と判定する。"""
    commit = _git(repo, "rev-parse", "HEAD")
    entry = {"path": "data/output/datasets/missing.gpkg", "sha256": "0" * 64}
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[entry])}
    )
    result = _check(repo, path)
    assert result.status == target.STATUS_INPUT_MISSING
    assert "missing.gpkg" in result.reasons[target.STATUS_INPUT_MISSING][0]


@pytest.mark.parametrize(
    "inputs",
    [[{"sha256": "0" * 64}], ["text"], "not_list"],
    ids=["no_path", "not_dict", "not_list"],
)
def test_input_missing_when_input_record_is_malformed(repo: Path, inputs: object) -> None:
    """入力の記録が不正（パスが無い等）な場合も入力欠落と判定する。"""
    commit = _git(repo, "rev-parse", "HEAD")
    provenance = _provenance(commit)
    provenance["inputs"] = inputs
    path = _write_result(repo, "a_results.json", {"provenance": provenance})
    assert _check(repo, path).status == target.STATUS_INPUT_MISSING


@pytest.mark.parametrize("inputs", [None, []], ids=["none", "empty"])
def test_missing_or_empty_inputs_are_not_checked(repo: Path, inputs: object) -> None:
    """入力の記録が無い・空なら入力は照合せず、ほかに問題が無ければ最新とする（既知の限界）。"""
    commit = _git(repo, "rev-parse", "HEAD")
    provenance = _provenance(commit)
    provenance["inputs"] = inputs
    path = _write_result(repo, "a_results.json", {"provenance": provenance})
    assert _check(repo, path).status == target.STATUS_UP_TO_DATE


def test_stale_input_when_hash_differs(repo: Path) -> None:
    """入力ファイルのハッシュが記録値と違えば要再実行（入力変更）と判定する。"""
    commit = _git(repo, "rev-parse", "HEAD")
    path = _write_result(
        repo,
        "a_results.json",
        {"provenance": _provenance(commit, inputs=[_input_entry(_sha256(b"dataset-v0"))])},
    )
    result = _check(repo, path)
    assert result.status == target.STATUS_STALE_INPUT


def test_stale_input_when_hash_not_recorded(repo: Path) -> None:
    """入力のハッシュが記録されていなければ、一致を確かめられないため要再実行とする。"""
    commit = _git(repo, "rev-parse", "HEAD")
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[{"path": INPUT_REL}])}
    )
    assert _check(repo, path).status == target.STATUS_STALE_INPUT


def test_hash_comparison_ignores_case(repo: Path) -> None:
    """記録されたハッシュが大文字でも一致と判定する。"""
    commit = _git(repo, "rev-parse", "HEAD")
    entry = _input_entry(_sha256(b"dataset-v1").upper())
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[entry])}
    )
    assert _check(repo, path).status == target.STATUS_UP_TO_DATE


@pytest.mark.parametrize(
    "changed_file",
    [
        "src/analysis/run_model.py",
        "src/common/util.py",
        "src/analysis/urban_params/canonical_grid.py",
    ],
    ids=["script", "common", "canonical_grid"],
)
def test_stale_code_when_watched_file_changed(repo: Path, changed_file: str) -> None:
    """生成スクリプトか既定の監視パスが変わっていれば要再実行（コード変更）と判定する。"""
    commit = _git(repo, "rev-parse", "HEAD")
    (repo / changed_file).write_text("VERSION = 2\n", encoding="utf-8")
    _commit_all(repo, "change")
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[_input_entry()])}
    )
    result = _check(repo, path)
    assert result.status == target.STATUS_STALE_CODE
    assert result.changed_files == [changed_file]


def test_unwatched_change_is_ignored_unless_extra_watch_path(repo: Path) -> None:
    """監視対象外の変更は無視し、`extra_watch_paths` で追加すれば検出する。"""
    commit = _git(repo, "rev-parse", "HEAD")
    (repo / "src" / "analysis" / "other.py").write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(repo, "change other")
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[_input_entry()])}
    )
    assert _check(repo, path).status == target.STATUS_UP_TO_DATE
    result = _check(repo, path, extra_watch_paths=("src/analysis/other.py",))
    assert result.status == target.STATUS_STALE_CODE
    assert result.changed_files == ["src/analysis/other.py"]


def test_uncommitted_working_tree_change_is_not_counted(repo: Path) -> None:
    """判定の基準は HEAD であり、未コミットの作業ツリーの変更は数えない。"""
    commit = _git(repo, "rev-parse", "HEAD")
    (repo / "src" / "common" / "util.py").write_text("VALUE = 9\n", encoding="utf-8")
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[_input_entry()])}
    )
    assert _check(repo, path).status == target.STATUS_UP_TO_DATE


def test_commit_on_other_branch_is_compared_by_tree(repo: Path) -> None:
    """HEAD の祖先でないコミット（squash merge 前の作業ブランチ）でも木の比較で判定する。"""
    _git(repo, "checkout", "-q", "-b", "work")
    (repo / "src" / "analysis" / "run_model.py").write_text("VERSION = 2\n", encoding="utf-8")
    branch_commit = _commit_all(repo, "work change")
    _git(repo, "checkout", "-q", "-")
    # 作業ブランチと同じ内容を別コミットとして取り込む（squash merge 相当）
    (repo / "src" / "analysis" / "run_model.py").write_text("VERSION = 2\n", encoding="utf-8")
    _commit_all(repo, "squashed")
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(branch_commit, inputs=[_input_entry()])}
    )
    assert _check(repo, path).status == target.STATUS_UP_TO_DATE


def test_stale_code_when_generated_with_dirty_tree(repo: Path) -> None:
    """未コミットの変更がある状態で生成された結果は、コードを復元できないため要再実行とする。"""
    commit = _git(repo, "rev-parse", "HEAD")
    path = _write_result(
        repo,
        "a_results.json",
        {"provenance": _provenance(commit, dirty=True, inputs=[_input_entry()])},
    )
    result = _check(repo, path)
    assert result.status == target.STATUS_STALE_CODE
    assert "未コミット" in result.reasons[target.STATUS_STALE_CODE][0]


@pytest.mark.parametrize(
    ("commit", "expected_word"),
    [(None, "記録されていない"), ("0" * 40, "ローカルに無い")],
    ids=["not_recorded", "not_found"],
)
def test_stale_code_when_commit_unavailable(
    repo: Path, commit: str | None, expected_word: str
) -> None:
    """記録コミットが無い・ローカルに無い場合は要再実行（コード変更）とし、理由を明記する。"""
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[_input_entry()])}
    )
    result = _check(repo, path)
    assert result.status == target.STATUS_STALE_CODE
    assert expected_word in result.reasons[target.STATUS_STALE_CODE][0]


def _code_record(repo: Path, extra_paths: tuple[str, ...] = ()) -> dict[str, object]:
    """来歴の生成側と同じ関数で、現在の作業ツリーのコードのハッシュを記録する。"""
    watch_paths = [target.script_module_to_path(SCRIPT_MODULE), *target.DEFAULT_WATCH_PATHS]
    return describe_code_files([*watch_paths, *extra_paths], repo)


def _hashed_provenance(repo: Path, commit: str | None, **kwargs: object) -> dict[str, object]:
    """コードのハッシュを持つ（新形式の）来歴を作る。"""
    provenance = _provenance(commit, inputs=[_input_entry()], **kwargs)
    provenance["code"] = _code_record(repo)
    return provenance


@pytest.mark.parametrize("commit", [None, "0" * 40], ids=["not_recorded", "not_found"])
def test_code_hash_judges_up_to_date_without_recorded_commit(
    repo: Path, commit: str | None
) -> None:
    """コードのハッシュがあれば、記録コミットが無い・ローカルに無くても最新と判定できる。"""
    path = _write_result(repo, "a_results.json", {"provenance": _hashed_provenance(repo, commit)})
    result = _check(repo, path)
    assert result.status == target.STATUS_UP_TO_DATE
    assert result.reasons == {}
    # 記録コミットは判定に使わなくても出力に残す
    assert result.recorded_commit == commit


@pytest.mark.parametrize(
    "changed_file",
    [
        "src/analysis/run_model.py",
        "src/common/util.py",
        "src/analysis/urban_params/canonical_grid.py",
    ],
    ids=["script", "common", "canonical_grid"],
)
def test_code_hash_detects_change_without_recorded_commit(repo: Path, changed_file: str) -> None:
    """記録コミットがローカルに無くても、ハッシュの不一致でコード変更を検出する。"""
    provenance = _hashed_provenance(repo, "0" * 40)
    (repo / changed_file).write_text("VERSION = 2\n", encoding="utf-8")
    _commit_all(repo, "change")
    path = _write_result(repo, "a_results.json", {"provenance": provenance})
    result = _check(repo, path)
    assert result.status == target.STATUS_STALE_CODE
    assert result.changed_files == [changed_file]
    assert result.reasons[target.STATUS_STALE_CODE] == [
        "生成時からコードが変更されている（1 ファイル）"
    ]


def test_code_hash_detects_added_and_deleted_files(repo: Path) -> None:
    """監視パス配下へのファイルの追加・削除も差分として検出する。"""
    provenance = _hashed_provenance(repo, "0" * 40)
    (repo / "src" / "common" / "added.py").write_text("NEW = 1\n", encoding="utf-8")
    (repo / "src" / "common" / "util.py").unlink()
    _commit_all(repo, "add and delete")
    path = _write_result(repo, "a_results.json", {"provenance": provenance})
    result = _check(repo, path)
    assert result.status == target.STATUS_STALE_CODE
    assert result.changed_files == ["src/common/added.py", "src/common/util.py"]


def test_code_hash_ignores_unwatched_and_uncommitted_changes(repo: Path) -> None:
    """ハッシュでの判定でも、監視対象外の変更と未コミットの作業ツリーの変更は数えない。"""
    provenance = _hashed_provenance(repo, "0" * 40)
    (repo / "src" / "analysis" / "other.py").write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(repo, "change other")
    (repo / "src" / "common" / "util.py").write_text("VALUE = 9\n", encoding="utf-8")
    path = _write_result(repo, "a_results.json", {"provenance": provenance})
    assert _check(repo, path).status == target.STATUS_UP_TO_DATE


def test_code_hash_ignores_crlf_in_working_tree(repo: Path) -> None:
    """生成時の作業ツリーが CRLF でも、HEAD の内容（LF）と同じコードなら最新と判定する。"""
    (repo / "src" / "common" / "util.py").write_bytes(b"VALUE = 1\r\n")
    provenance = _hashed_provenance(repo, "0" * 40)
    path = _write_result(repo, "a_results.json", {"provenance": provenance})
    assert _check(repo, path).status == target.STATUS_UP_TO_DATE


def test_unhashed_watch_path_falls_back_to_tree_comparison(repo: Path) -> None:
    """ハッシュの記録が無い監視パスだけは、記録コミットとの木の比較で判定する。"""
    commit = _git(repo, "rev-parse", "HEAD")
    provenance = _hashed_provenance(repo, commit)
    (repo / "src" / "analysis" / "other.py").write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(repo, "change other")
    path = _write_result(repo, "a_results.json", {"provenance": provenance})
    result = _check(repo, path, extra_watch_paths=("src/analysis/other.py",))
    assert result.status == target.STATUS_STALE_CODE
    assert result.changed_files == ["src/analysis/other.py"]


def test_unhashed_watch_path_without_commit_names_the_paths(repo: Path) -> None:
    """記録の無い監視パスがあり記録コミットも無ければ、要再実行とし対象のパスを理由に残す。"""
    path = _write_result(repo, "a_results.json", {"provenance": _hashed_provenance(repo, "0" * 40)})
    result = _check(repo, path, extra_watch_paths=("src/analysis/other.py/",))
    assert result.status == target.STATUS_STALE_CODE
    reason = result.reasons[target.STATUS_STALE_CODE][0]
    assert "ハッシュの記録が無い監視パス" in reason
    assert "src/analysis/other.py" in reason
    assert "ローカルに無い" in reason
    # ハッシュの記録がある範囲は判定でき、差分は無い
    assert result.changed_files == []


def test_code_hash_keeps_dirty_and_script_reasons(repo: Path) -> None:
    """ハッシュがあっても、dirty と生成スクリプトの記録漏れは従来どおり要再実行とする。"""
    path = _write_result(
        repo,
        "a_results.json",
        {"provenance": _hashed_provenance(repo, "0" * 40, dirty=True, script=None)},
    )
    reasons = _check(repo, path).reasons[target.STATUS_STALE_CODE]
    assert "未コミット" in reasons[0]
    assert "生成スクリプト" in reasons[1]


@pytest.mark.parametrize(
    "code",
    [
        None,
        "text",
        {"watch_paths": ["src/common"]},
        {"watch_paths": ["src/common"], "files": [{"path": "src/common/util.py"}]},
        {"watch_paths": "src/common", "files": []},
    ],
    ids=["null", "not_dict", "no_files", "no_sha256", "watch_paths_not_list"],
)
def test_malformed_code_record_falls_back_to_commit(repo: Path, code: object) -> None:
    """コードのハッシュが無い・不正な場合は、旧形式として記録コミットで判定する。"""
    provenance = _provenance("0" * 40, inputs=[_input_entry()])
    provenance["code"] = code
    path = _write_result(repo, "a_results.json", {"provenance": provenance})
    result = _check(repo, path)
    assert result.status == target.STATUS_STALE_CODE
    assert "ローカルに無い" in result.reasons[target.STATUS_STALE_CODE][0]


def test_head_code_hashes_are_cached(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同じ監視パスの HEAD のハッシュは、結果ファイルが複数あっても1回だけ計算する。"""
    git = target.GitRepository(repo)
    calls: list[tuple[str, ...]] = []
    original = git._list_head_code_hashes

    def counting(paths: tuple[str, ...]) -> dict[str, str] | None:
        calls.append(paths)
        return original(paths)

    monkeypatch.setattr(git, "_list_head_code_hashes", counting)
    provenance = _hashed_provenance(repo, "0" * 40)
    for name in ("a_results.json", "b_results.json"):
        path = _write_result(repo, name, {"provenance": provenance})
        assert target.check_result_file(path, repo, repo, git, {}).status == (
            target.STATUS_UP_TO_DATE
        )
    assert len(calls) == 1


def test_extra_watch_path_inside_recorded_range_uses_hash(repo: Path) -> None:
    """記録範囲の配下を追加で監視しても、記録コミット無しでハッシュにより判定できる。"""
    provenance = _hashed_provenance(repo, "0" * 40)
    path = _write_result(repo, "a_results.json", {"provenance": provenance})
    extra = ("src/common/util.py",)
    assert _check(repo, path, extra_watch_paths=extra).status == target.STATUS_UP_TO_DATE

    (repo / "src" / "common" / "util.py").write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(repo, "change")
    result = _check(repo, path, extra_watch_paths=extra)
    assert result.status == target.STATUS_STALE_CODE
    assert result.changed_files == ["src/common/util.py"]
    assert "ハッシュの記録が無い" not in "".join(result.reasons[target.STATUS_STALE_CODE])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r".\src\common\util.py", "src/common/util.py"),
        ("././src/common/", "src/common"),
        ("src/common", "src/common"),
    ],
    ids=["powershell_completion", "repeated_dot_slash", "already_normalized"],
)
def test_normalize_watch_path(raw: str, expected: str) -> None:
    """区切り文字・先頭の `./`・末尾の `/` をそろえる。"""
    assert target.normalize_watch_path(raw) == expected


def test_dot_slash_extra_watch_path_inside_recorded_range_uses_hash(repo: Path) -> None:
    """`.\\` 付きで記録範囲の配下を指定しても、記録コミット無しでハッシュにより判定できる。"""
    path = _write_result(repo, "a_results.json", {"provenance": _hashed_provenance(repo, "0" * 40)})
    result = _check(repo, path, extra_watch_paths=(r".\src\common\util.py",))
    assert result.status == target.STATUS_UP_TO_DATE


def test_extra_watch_path_wider_than_recorded_range_uses_tree(repo: Path) -> None:
    """記録範囲より広いパスは記録が無いファイルを含みうるため、木の比較に回す。"""
    path = _write_result(repo, "a_results.json", {"provenance": _hashed_provenance(repo, "0" * 40)})
    result = _check(repo, path, extra_watch_paths=("src/analysis/",))
    assert result.status == target.STATUS_STALE_CODE
    reason = result.reasons[target.STATUS_STALE_CODE][0]
    assert "ハッシュの記録が無い監視パスがあり（src/analysis）" in reason


def test_stale_code_when_head_hashes_unavailable(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HEAD のコードのハッシュを取得できない場合は要再実行とし、理由を残す。"""
    git = target.GitRepository(repo)
    monkeypatch.setattr(git, "head_code_hashes", lambda paths: None)
    path = _write_result(repo, "a_results.json", {"provenance": _hashed_provenance(repo, "0" * 40)})
    result = target.check_result_file(path, repo, repo, git, {})
    assert result.status == target.STATUS_STALE_CODE
    assert result.reasons[target.STATUS_STALE_CODE] == ["HEAD のコードのハッシュを取得できない"]
    assert result.changed_files == []


def test_head_code_hashes_returns_none_for_missing_object(repo: Path) -> None:
    """git に無いオブジェクト（cat-file の missing 応答）は失敗として扱う。"""
    git = target.GitRepository(repo)
    assert git._hash_blobs(["0" * 40]) is False
    assert git._blob_hash_cache == {}


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (128, b""),
        (0, b"OID blob x\nVALUE = 1\n\n"),
        (0, b"OID blob 100\nVALUE = 1\n"),
        (0, b"\xff\xfe blob 3\nabc\n"),
        (0, b""),
    ],
    ids=["exit_error", "size_not_digit", "truncated", "undecodable_id", "empty"],
)
def test_hash_blobs_rejects_broken_output(
    repo: Path, monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: bytes
) -> None:
    """cat-file が異常終了・想定外の形式の出力を返した場合は、例外にせず失敗として返す。"""
    oid = "a" * 40
    completed = subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout.replace(b"OID", oid.encode("ascii"))
    )
    monkeypatch.setattr(target.subprocess, "run", lambda *args, **kwargs: completed)
    assert target.GitRepository(repo)._hash_blobs([oid]) is False


def test_stale_code_when_script_not_recorded(repo: Path) -> None:
    """生成スクリプトが記録されていない場合は、既定の監視パスだけを監視し理由を残す。"""
    commit = _git(repo, "rev-parse", "HEAD")
    path = _write_result(
        repo,
        "a_results.json",
        {"provenance": _provenance(commit, script=None, inputs=[_input_entry()])},
    )
    result = _check(repo, path)
    assert result.status == target.STATUS_STALE_CODE
    assert "生成スクリプト" in result.reasons[target.STATUS_STALE_CODE][0]


# --- 優先順位・理由の保持 ---


def test_priority_keeps_all_reasons(repo: Path) -> None:
    """複数の分類に当たる場合は優先順位の高い分類を主分類とし、理由はすべて残す。"""
    commit = _git(repo, "rev-parse", "HEAD")
    (repo / "src" / "common" / "util.py").write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(repo, "change")
    entries = [
        {"path": "data/output/datasets/missing.gpkg", "sha256": "0" * 64},
        _input_entry(_sha256(b"dataset-v0")),
    ]
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=entries)}
    )
    result = _check(repo, path)
    assert result.status == target.STATUS_INPUT_MISSING
    statuses = [item["status"] for item in result.to_dict()["reasons"]]
    assert statuses == [
        target.STATUS_INPUT_MISSING,
        target.STATUS_STALE_INPUT,
        target.STATUS_STALE_CODE,
    ]


def test_hash_is_computed_once_per_input(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同じ入力ファイルを共有する結果が複数あっても、ハッシュは1回だけ計算する。"""
    calls: list[Path] = []
    original = target.compute_file_sha256

    def counting(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(target, "compute_file_sha256", counting)
    commit = _git(repo, "rev-parse", "HEAD")
    hash_cache: dict[Path, str] = {}
    for name in ("a_results.json", "b_results.json"):
        path = _write_result(
            repo, name, {"provenance": _provenance(commit, inputs=[_input_entry()])}
        )
        _check(repo, path, hash_cache=hash_cache)
    assert len(calls) == 1


def test_absolute_input_path_is_used_as_is(repo: Path, tmp_path: Path) -> None:
    """プロジェクト外の入力（絶対パスで記録）は、そのパスのファイルで判定する。"""
    outside = tmp_path / "outside.gpkg"
    outside.write_bytes(b"outside")
    commit = _git(repo, "rev-parse", "HEAD")
    entry = {"path": outside.as_posix(), "sha256": _sha256(b"outside")}
    path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[entry])}
    )
    assert _check(repo, path).status == target.STATUS_UP_TO_DATE


def test_data_root_is_used_for_relative_inputs(repo: Path, tmp_path: Path) -> None:
    """相対パスの入力は `data_root` を基準に解決する（別の作業ツリーの入力を読む用途）。"""
    data_root = tmp_path / "other_checkout"
    (data_root / "data" / "output" / "datasets").mkdir(parents=True)
    (data_root / INPUT_REL).write_bytes(b"other")
    commit = _git(repo, "rev-parse", "HEAD")
    path = _write_result(
        repo,
        "a_results.json",
        {"provenance": _provenance(commit, inputs=[_input_entry(_sha256(b"other"))])},
    )
    git = target.GitRepository(repo)
    result = target.check_result_file(path, repo, data_root, git, {})
    assert result.status == target.STATUS_UP_TO_DATE


# --- 走査・出力 ---


def test_find_result_files_matches_only_results_json(tmp_path: Path) -> None:
    """`*_results.json` だけを再帰的に、パス順で拾う。"""
    for relative in ("b/x_results.json", "a/y_results.json", "a/summary.json", "a/z_results.csv"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    found = [path.relative_to(tmp_path).as_posix() for path in target.find_result_files(tmp_path)]
    assert found == ["a/y_results.json", "b/x_results.json"]


def test_markdown_report_lists_counts_and_problems() -> None:
    """Markdown には全分類の件数表と、問題のある結果の理由を載せる。"""
    stale = target.StalenessResult(path="data/output/a_results.json")
    stale.add_reason(target.STATUS_STALE_INPUT, "入力ファイルが変更されている: x.gpkg")
    fresh = target.StalenessResult(path="data/output/b_results.json")
    report = target.build_report_data(
        [stale, fresh], "abc123", "data/output", target.dt.datetime(2026, 10, 21)
    )
    assert report["counts"][target.STATUS_STALE_INPUT] == 1
    assert report["counts"][target.STATUS_UP_TO_DATE] == 1
    markdown = target.format_markdown_report(report)
    for status in target.STATUS_ORDER:
        assert f"| {target.STATUS_LABELS[status]} |" in markdown
    assert "- `data/output/a_results.json`: 入力ファイルが変更されている: x.gpkg" in markdown
    assert "<details><summary>最新（1 件）</summary>" in markdown


def test_main_writes_json_and_markdown(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main は走査結果を JSON と Markdown に書き出し、結果ファイルは書き換えない。"""
    commit = _git(repo, "rev-parse", "HEAD")
    result_path = _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[_input_entry()])}
    )
    _write_result(repo, "b_results.json", {"sample_size": 1})
    before = result_path.read_bytes()
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    exit_code = target.main(
        ["--output-json", "out/staleness.json", "--output-md", "out/staleness.md"]
    )
    assert exit_code == 0
    report = json.loads((repo / "out" / "staleness.json").read_text(encoding="utf-8"))
    assert report["head_commit"] == commit
    assert [entry["status"] for entry in report["results"]] == [
        target.STATUS_UP_TO_DATE,
        target.STATUS_NO_PROVENANCE,
    ]
    assert (repo / "out" / "staleness.md").read_text(encoding="utf-8").startswith("## ")
    assert result_path.read_bytes() == before
    assert "判定件数 2 件" in capsys.readouterr().err


def test_main_prints_markdown_without_output_md(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--output-md` を省略すると Markdown を標準出力に出す。"""
    _write_result(repo, "a_results.json", {"sample_size": 1})
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    assert target.main([]) == 0
    assert "## 分析結果の陳腐化検出" in capsys.readouterr().out


def test_main_fails_when_results_root_missing(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """走査先が無ければ終了コード1で止める。"""
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    assert target.main(["--results-root", "no_such_dir"]) == 1
    assert "走査先" in capsys.readouterr().err


def test_main_fails_outside_git_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """git の HEAD を取得できなければ終了コード1で止める。"""
    (tmp_path / "data" / "output").mkdir(parents=True)
    monkeypatch.setattr(target, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert target.main([]) == 1
    assert "HEAD" in capsys.readouterr().err


# --- 報告モード（前回マーカーとの差分） ---

RUN_DATE = target.dt.date(2026, 10, 26)


def _report(statuses: dict[str, str]) -> dict[str, object]:
    """結果パス → 分類から判定結果（`build_report_data` の戻り値）を作る。"""
    results = []
    for path, status in statuses.items():
        result = target.StalenessResult(path=path)
        if status != target.STATUS_UP_TO_DATE:
            result.add_reason(status, f"理由-{status}")
        results.append(result)
    return target.build_report_data(
        results, "abc123", "data/output", target.dt.datetime(2026, 10, 26)
    )


def _issue_json(tmp_path: Path, body: str, comments: list[str]) -> Path:
    """`gh issue view --json body,comments` 相当の保存ファイルを作る。"""
    path = tmp_path / "issue.json"
    data = {"body": body, "comments": [{"body": text} for text in comments]}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_marker_round_trip_with_special_characters() -> None:
    """空白・`=`・`>` を含むパスでもマーカーから状態を復元できる。"""
    state = {
        "data/output/a b/x=1_results.json": target.STATUS_STALE_CODE,
        "data/output/日本語->_results.json": target.STATUS_INPUT_MISSING,
    }
    marker = target.format_state_marker(state)
    assert marker.count("-->") == 1
    assert target.extract_latest_state([f"本文\n{marker}\n"]) == state


def test_extract_latest_state_uses_last_marker() -> None:
    """本文とコメントのうち、最後に現れたマーカーを前回状態とする。"""
    first = target.format_state_marker({"a_results.json": target.STATUS_STALE_CODE})
    last = target.format_state_marker({})
    assert target.extract_latest_state([first, "ユーザーの補足", last, "補足2"]) == {}
    assert target.extract_latest_state(["マーカーなし"]) is None


def test_extract_latest_state_rejects_malformed_marker() -> None:
    """マーカーの中身が `パス=分類` の形式でなければ例外にする。"""
    with pytest.raises(ValueError, match="形式"):
        target.extract_latest_state(["<!-- result-staleness-state: a_results.json=unknown -->"])


def test_diff_states_classifies_new_resolved_changed_continuing() -> None:
    """新規・解消・分類変化・継続を区別する。"""
    previous = {
        "keep": target.STATUS_NO_PROVENANCE,
        "change": target.STATUS_INPUT_MISSING,
        "fixed": target.STATUS_STALE_CODE,
    }
    current = {
        "keep": target.STATUS_NO_PROVENANCE,
        "change": target.STATUS_STALE_INPUT,
        "added": target.STATUS_STALE_CODE,
    }
    diff = target.diff_states(previous, current)
    assert diff.new == {"added": target.STATUS_STALE_CODE}
    assert diff.resolved == {"fixed": target.STATUS_STALE_CODE}
    assert diff.changed == {"change": (target.STATUS_INPUT_MISSING, target.STATUS_STALE_INPUT)}
    assert diff.continuing == {"keep": target.STATUS_NO_PROVENANCE}
    assert diff.has_change


def test_build_report_text_new_issue_when_problems_exist() -> None:
    """報告 Issue が無く問題があれば、マーカーとフッタつきの起票本文を返す。"""
    report = _report({"a": target.STATUS_STALE_CODE, "b": target.STATUS_UP_TO_DATE})
    exit_code, text = target.build_report_text(report, None, RUN_DATE)
    assert exit_code == target.EXIT_REPORT_WRITTEN
    assert text.rstrip().endswith(target.ISSUE_FOOTER)
    assert target.extract_latest_state([text]) == {"a": target.STATUS_STALE_CODE}


def test_build_report_text_no_issue_and_no_problem() -> None:
    """報告 Issue が無く問題も無ければ、何も書き出さない。"""
    report = _report({"a": target.STATUS_UP_TO_DATE})
    assert target.build_report_text(report, None, RUN_DATE) == (target.EXIT_NO_CHANGE, None)


def test_build_report_text_diff_comment() -> None:
    """前回から差分があれば、新規・解消・継続を載せた差分コメントを返す。"""
    report = _report(
        {
            "keep": target.STATUS_NO_PROVENANCE,
            "added": target.STATUS_STALE_INPUT,
            "fixed": target.STATUS_UP_TO_DATE,
        }
    )
    previous = {"keep": target.STATUS_NO_PROVENANCE, "fixed": target.STATUS_STALE_CODE}
    exit_code, text = target.build_report_text(report, previous, RUN_DATE)
    assert exit_code == target.EXIT_REPORT_WRITTEN
    assert "## 陳腐化検出 差分報告 (2026-10-26)" in text
    assert "- `added`（要再実行（入力変更））: 理由-stale_input" in text
    assert "- `fixed`（前回: 要再実行（コード変更））" in text
    assert "### 継続（1 件）" in text
    assert text.rstrip().endswith(target.COMMENT_FOOTER)
    assert target.extract_latest_state([text]) == {
        "keep": target.STATUS_NO_PROVENANCE,
        "added": target.STATUS_STALE_INPUT,
    }


def test_build_report_text_status_change_counts_as_diff() -> None:
    """件数が同じでも分類が変われば差分コメントを返す。"""
    report = _report({"a": target.STATUS_STALE_INPUT})
    exit_code, text = target.build_report_text(report, {"a": target.STATUS_INPUT_MISSING}, RUN_DATE)
    assert exit_code == target.EXIT_REPORT_WRITTEN
    assert "- `a`: 入力欠落 → 要再実行（入力変更）" in text


def test_build_report_text_no_change() -> None:
    """前回と同じ問題だけが残っていれば、何も書き出さない。"""
    report = _report({"a": target.STATUS_STALE_CODE, "b": target.STATUS_UP_TO_DATE})
    previous = {"a": target.STATUS_STALE_CODE}
    assert target.build_report_text(report, previous, RUN_DATE) == (target.EXIT_NO_CHANGE, None)


def test_build_report_text_all_resolved() -> None:
    """前回の問題がすべて解消すれば、解消一覧と空のマーカーを返す。"""
    report = _report({"a": target.STATUS_UP_TO_DATE})
    exit_code, text = target.build_report_text(report, {"a": target.STATUS_STALE_CODE}, RUN_DATE)
    assert exit_code == target.EXIT_ALL_RESOLVED
    assert "- `a`（前回: 要再実行（コード変更））" in text
    assert target.extract_latest_state([text]) == {}


def test_build_report_text_previous_empty_and_no_problem() -> None:
    """前回も今回も問題が無ければ（解消済みの Issue）、何も書き出さない。"""
    report = _report({"a": target.STATUS_UP_TO_DATE})
    assert target.build_report_text(report, {}, RUN_DATE) == (target.EXIT_NO_CHANGE, None)


@pytest.mark.parametrize(
    "content",
    ["", "  \n", "{not json", "[]", '{"body": "x", "comments": "text"}'],
    ids=["empty", "blank", "invalid_json", "not_object", "comments_not_list"],
)
def test_load_previous_state_rejects_broken_file(tmp_path: Path, content: str) -> None:
    """保存ファイルが空・不正なら例外にする（前回状態を推測しない）。"""
    path = tmp_path / "issue.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        target.load_previous_state(path)


def test_load_previous_state_requires_marker(tmp_path: Path) -> None:
    """マーカーが1つも無ければ例外にする。"""
    path = _issue_json(tmp_path, "本文", ["補足"])
    with pytest.raises(ValueError, match="マーカー"):
        target.load_previous_state(path)


def test_load_previous_state_reads_comments(tmp_path: Path) -> None:
    """本文よりコメントのマーカーを優先し、最新のコメントの状態を返す。"""
    body = target.format_state_marker({"a": target.STATUS_STALE_CODE})
    comment = target.format_state_marker({"b": target.STATUS_INPUT_MISSING})
    path = _issue_json(tmp_path, body, [comment])
    assert target.load_previous_state(path) == {"b": target.STATUS_INPUT_MISSING}


def test_main_report_mode_with_previous_issue(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """報告モードで前回の Issue を渡すと、差分コメントを書き出して終了コード0を返す。"""
    _write_result(repo, "a_results.json", {"sample_size": 1})
    issue_path = _issue_json(tmp_path, target.format_state_marker({}), [])
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    exit_code = target.main(
        [
            "--output-md",
            "out/staleness.md",
            "--report-output",
            "out/report.md",
            "--previous-issue-json",
            str(issue_path),
        ]
    )
    assert exit_code == target.EXIT_REPORT_WRITTEN
    text = (repo / "out" / "report.md").read_text(encoding="utf-8")
    assert "data/output/analysis/a_results.json" in text
    assert text.rstrip().endswith(target.COMMENT_FOOTER)


def test_main_report_mode_stops_before_checking_when_issue_unreadable(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """報告 Issue を読めなければ、判定も書き出しもせずに終了コード1を返す。"""
    empty = tmp_path / "issue.json"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)

    def must_not_scan(_root: Path) -> list[Path]:
        pytest.fail("報告 Issue を読めないまま判定に進んではいけない")

    monkeypatch.setattr(target, "find_result_files", must_not_scan)
    exit_code = target.main(
        ["--report-output", "out/report.md", "--previous-issue-json", str(empty)]
    )
    assert exit_code == target.EXIT_FAILURE
    assert not (repo / "out" / "report.md").exists()


def test_main_report_mode_no_change_writes_nothing(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """報告 Issue が無く問題も無ければ、終了コード3で本文を書き出さない。"""
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    exit_code = target.main(["--output-md", "out/staleness.md", "--report-output", "out/report.md"])
    assert exit_code == target.EXIT_NO_CHANGE
    assert not (repo / "out" / "report.md").exists()


def test_previous_issue_json_requires_report_output(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--previous-issue-json` だけを指定すると引数エラーにする。"""
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    with pytest.raises(SystemExit):
        target.main(["--previous-issue-json", "issue.json"])


def test_main_report_mode_all_resolved(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """前回の問題がすべて解消すれば、解消一覧を書き出して終了コード4を返す。"""
    commit = _git(repo, "rev-parse", "HEAD")
    _write_result(
        repo, "a_results.json", {"provenance": _provenance(commit, inputs=[_input_entry()])}
    )
    previous = target.format_state_marker(
        {"data/output/analysis/a_results.json": target.STATUS_STALE_CODE}
    )
    issue_path = _issue_json(tmp_path, previous, [])
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    exit_code = target.main(
        [
            "--output-md",
            "out/staleness.md",
            "--report-output",
            "out/report.md",
            "--previous-issue-json",
            str(issue_path),
        ]
    )
    assert exit_code == target.EXIT_ALL_RESOLVED
    text = (repo / "out" / "report.md").read_text(encoding="utf-8")
    assert "- `data/output/analysis/a_results.json`（前回: 要再実行（コード変更））" in text
    assert target.extract_latest_state([text]) == {}


def test_main_report_mode_fails_without_marker(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """報告 Issue にマーカーが無ければ、書き出さずに終了コード1を返す。"""
    issue_path = _issue_json(tmp_path, "手で書き換えた本文", ["補足"])
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    exit_code = target.main(
        ["--report-output", "out/report.md", "--previous-issue-json", str(issue_path)]
    )
    assert exit_code == target.EXIT_FAILURE
    assert not (repo / "out" / "report.md").exists()
    assert "マーカー" in capsys.readouterr().err


# --- 報告モードのブランチ制限 ---


def _forbid_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """結果ファイルの走査に進んだらテストを失敗させる。"""

    def must_not_scan(_root: Path) -> list[Path]:
        pytest.fail("main 以外のブランチで報告モードの判定に進んではいけない")

    monkeypatch.setattr(target, "find_result_files", must_not_scan)


@pytest.mark.parametrize("checkout", ["branch", "detached"])
def test_main_report_mode_refuses_outside_main(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    checkout: str,
) -> None:
    """main 以外では、報告 Issue を渡しても判定・書き出しをせずに終了コード1を返す。"""
    if checkout == "branch":
        _git(repo, "checkout", "-q", "-b", "feature/work")
        expected = "feature/work"
    else:
        _git(repo, "checkout", "-q", "--detach")
        expected = "detached HEAD"
    issue_path = _issue_json(tmp_path, target.format_state_marker({}), [])
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    _forbid_scan(monkeypatch)
    exit_code = target.main(
        ["--report-output", "out/report.md", "--previous-issue-json", str(issue_path)]
    )
    assert exit_code == target.EXIT_FAILURE
    assert not (repo / "out" / "report.md").exists()
    err = capsys.readouterr().err
    assert f"現在: {expected}" in err
    assert "--report-output を外して" in err


def test_main_report_mode_refuses_new_issue_outside_main(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """報告 Issue が無い（新規起票の）場合も、main 以外では本文を書き出さない。"""
    _git(repo, "checkout", "-q", "-b", "feature/work")
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    _forbid_scan(monkeypatch)
    assert target.main(["--report-output", "out/report.md"]) == target.EXIT_FAILURE
    assert not (repo / "out" / "report.md").exists()


def test_main_without_report_output_runs_outside_main(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--report-output` なしの判定だけの実行は、main 以外のブランチでも動く。"""
    _git(repo, "checkout", "-q", "-b", "feature/work")
    _write_result(repo, "a_results.json", {"sample_size": 1})
    monkeypatch.setattr(target, "PROJECT_ROOT", repo)
    assert target.main(["--output-json", "out/staleness.json"]) == target.EXIT_REPORT_WRITTEN
    report = json.loads((repo / "out" / "staleness.json").read_text(encoding="utf-8"))
    assert [entry["status"] for entry in report["results"]] == [target.STATUS_NO_PROVENANCE]


def test_current_branch(repo: Path) -> None:
    """ブランチ名を返し、detached HEAD では None を返す。"""
    git = target.GitRepository(repo)
    assert git.current_branch() == "main"
    _git(repo, "checkout", "-q", "--detach")
    assert git.current_branch() is None


def test_main_report_mode_outside_git_reports_head_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """git 自体を使えない場合は、ブランチの問題（detached HEAD）と取り違えずに止める。"""
    (tmp_path / "data" / "output").mkdir(parents=True)
    monkeypatch.setattr(target, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert target.main(["--report-output", "out/report.md"]) == target.EXIT_FAILURE
    err = capsys.readouterr().err
    assert "HEAD を取得できない" in err
    assert "detached HEAD" not in err
