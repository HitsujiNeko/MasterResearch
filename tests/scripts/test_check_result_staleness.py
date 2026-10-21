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
    (root / "data" / "output" / "datasets").mkdir(parents=True)
    (root / INPUT_REL).write_bytes(b"dataset-v1")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
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
    ["src/analysis/run_model.py", "src/common/util.py"],
    ids=["script", "common"],
)
def test_stale_code_when_watched_file_changed(repo: Path, changed_file: str) -> None:
    """生成スクリプトか src/common/ が変わっていれば要再実行（コード変更）と判定する。"""
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


def test_stale_code_when_script_not_recorded(repo: Path) -> None:
    """生成スクリプトが記録されていない場合は、src/common/ だけを監視し理由を残す。"""
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
