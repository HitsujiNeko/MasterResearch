"""scripts/check_reproducibility.py（分析の再現性チェック）のテスト。

再実行の部分は、`tmp_path` に作ったダミーの分析モジュールを実際にサブプロセスで
実行して確認する（実際の分析スクリプトは時間がかかるため動かさない）。
実リポジトリの `data/output/` には書き込まない。
対象は ``src`` パッケージ外のスクリプトのため、``tests/scripts`` との import 名の衝突を
避けるよう、ファイルパスを指定して読み込む。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_reproducibility.py"


def _load_target() -> ModuleType:
    """対象スクリプトをモジュールとして読み込む。"""
    spec = importlib.util.spec_from_file_location("check_reproducibility", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


target = _load_target()

# ダミーの分析モジュール。`--value` の値を r2 として結果 JSON に書き、`--fail` で異常終了する
_FAKE_ANALYSIS = """\
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--value", type=float, default=0.5)
parser.add_argument("--fail", action="store_true")
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
print("fake analysis running")
if args.fail:
    print("boom", file=sys.stderr)
    sys.exit(3)
args.output_dir.mkdir(parents=True, exist_ok=True)
result = {
    "sample_size": 10,
    "features": ["A", "B"],
    "random_split": {"linear_regression": {"metrics": {"r2": args.value}}},
    "outputs": {"csv": str(args.output_dir / "x.csv")},
    "provenance": {"packages": {"numpy": "2.0.0"}},
}
(args.output_dir / "fake_results.json").write_text(json.dumps(result), encoding="utf-8")
"""

REFERENCE = {
    "sample_size": 10,
    "features": ["A", "B"],
    "random_split": {"linear_regression": {"metrics": {"r2": 0.5}}},
    "outputs": {"csv": "data/output/old/x.csv"},
    "provenance": {"packages": {"numpy": "1.26.4"}},
}


def _target(**overrides: object) -> object:
    """テスト用の対象構成を作る。"""
    values: dict[str, object] = {
        "name": "fake",
        "module": "fake_pkg.fake_analysis",
        "args": (),
        "reference_results": "data/output/ref/fake_results.json",
        "compare_keys": ("sample_size", "features", "random_split"),
    }
    values.update(overrides)
    return target.ReproducibilityTarget(**values)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """ダミーの分析モジュールと保存済み結果を持つ一時プロジェクト。"""
    root = tmp_path / "project"
    package = root / "fake_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "fake_analysis.py").write_text(_FAKE_ANALYSIS, encoding="utf-8")
    reference = root / "data" / "output" / "ref" / "fake_results.json"
    reference.parent.mkdir(parents=True)
    reference.write_text(json.dumps(REFERENCE), encoding="utf-8")
    return root


def _write_config(root: Path, targets: list[dict[str, object]]) -> Path:
    """設定ファイルを書き出す。"""
    path = root / "targets.json"
    path.write_text(json.dumps({"targets": targets}), encoding="utf-8")
    return path


def _config_entry(**overrides: object) -> dict[str, object]:
    """設定ファイルの1構成を作る。"""
    entry: dict[str, object] = {
        "name": "fake",
        "module": "fake_pkg.fake_analysis",
        "args": [],
        "reference_results": "data/output/ref/fake_results.json",
        "compare_keys": ["sample_size", "features", "random_split"],
    }
    entry.update(overrides)
    return entry


# --- 照合 ---


def test_flatten_values_skips_outputs_and_paths() -> None:
    """葉まで平らにし、出力一覧とパス類のキーは除く。"""
    value = {
        "a": {"b": [1, {"c": 2}]},
        "outputs": {"x": "y"},
        "dataset_path": "data/x.gpkg",
    }
    assert target.flatten_values(value) == {"a.b[0]": 1, "a.b[1].c": 2}


@pytest.mark.parametrize(
    ("reference", "rerun", "expected"),
    [
        (1.0, 1.0 + 1e-7, True),
        (1.0, 1.0 + 1e-5, False),
        (0.0, 1e-10, True),
        (0.0, 1e-8, False),
        (10, 10.0, True),
        (True, 1, False),
        (True, True, True),
        ("A", "A", True),
        ("1", 1, False),
        (None, None, True),
    ],
    ids=[
        "within_rel",
        "beyond_rel",
        "within_abs",
        "beyond_abs",
        "int_float",
        "bool_vs_int",
        "bool",
        "str",
        "str_vs_number",
        "none",
    ],
)
def test_values_match(reference: object, rerun: object, expected: bool) -> None:
    """数値は許容誤差つき、それ以外は型と値の完全一致で判定する。"""
    assert target.values_match(reference, rerun, 1e-9, 1e-6) is expected


def test_compare_results_reports_value_and_missing_keys() -> None:
    """値の違いと、片方にしかないキーを不一致として列挙する。"""
    reference = {"features": ["A", "B"], "random_split": {"r2": 0.5}, "ignored": 1}
    rerun = {"features": ["A"], "random_split": {"r2": 0.6, "rmse": 1.0}, "ignored": 2}
    count, mismatches = target.compare_results(
        reference, rerun, _target(compare_keys=("features", "random_split"))
    )
    assert count == 4
    reasons = {item["key"]: item["reason"] for item in mismatches}
    assert reasons == {
        "features[1]": "再実行結果に無い",
        "random_split.r2": "値が違う",
        "random_split.rmse": "保存済み結果に無い",
    }


def test_compare_results_matches_identical_content() -> None:
    """同じ内容なら不一致は無い（出力パスの違いは無視する）。"""
    rerun = dict(REFERENCE, outputs={"csv": "/tmp/elsewhere/x.csv"})
    count, mismatches = target.compare_results(REFERENCE, rerun, _target())
    assert count == 4
    assert mismatches == []


def test_compare_packages() -> None:
    """ライブラリ版の差を返し、来歴が無ければ比較不能（None）とする。"""
    rerun = {"provenance": {"packages": {"numpy": "2.0.0", "shap": "0.48.0"}}}
    assert target.compare_packages(REFERENCE, rerun) == {
        "numpy": {"reference": "1.26.4", "rerun": "2.0.0"},
        "shap": {"reference": None, "rerun": "0.48.0"},
    }
    assert target.compare_packages({"sample_size": 1}, rerun) is None


# --- 設定の検証・作業先の保護 ---


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": ""}, "name"),
        ({"module": 1}, "module"),
        ({"args": "--x"}, "args"),
        ({"args": ["--output-dir", "x"]}, "--output-dir"),
        ({"args": ["--output-dir=x"]}, "--output-dir"),
        ({"reference_results": None}, "reference_results"),
        ({"compare_keys": []}, "compare_keys"),
        ({"abs_tolerance": -1}, "abs_tolerance"),
        ({"rel_tolerance": True}, "rel_tolerance"),
    ],
    ids=[
        "empty_name",
        "module_not_str",
        "args_not_list",
        "output_dir",
        "output_dir_equals",
        "no_reference",
        "empty_compare_keys",
        "negative_tolerance",
        "bool_tolerance",
    ],
)
def test_parse_target_rejects_invalid_entry(overrides: dict[str, object], message: str) -> None:
    """必須項目の欠落・型の不正・`--output-dir` の指定を拒否する。"""
    with pytest.raises(ValueError, match=message):
        target.parse_target(_config_entry(**overrides), 0)


def test_parse_target_applies_defaults() -> None:
    """省略した照合キー・許容誤差には既定値を使う。"""
    entry = _config_entry()
    del entry["compare_keys"]
    parsed = target.parse_target(entry, 0)
    assert parsed.compare_keys == target.DEFAULT_COMPARE_KEYS
    assert parsed.abs_tolerance == target.DEFAULT_ABS_TOLERANCE
    assert parsed.rel_tolerance == target.DEFAULT_REL_TOLERANCE


def test_load_targets_rejects_duplicate_names(tmp_path: Path) -> None:
    """構成名の重複を拒否する。"""
    config = _write_config(tmp_path, [_config_entry(), _config_entry()])
    with pytest.raises(ValueError, match="重複"):
        target.load_targets(config)


def test_load_targets_requires_targets_list(tmp_path: Path) -> None:
    """`targets` が無い設定ファイルを拒否する。"""
    config = tmp_path / "targets.json"
    config.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="targets"):
        target.load_targets(config)


def test_select_targets() -> None:
    """`--all` は全構成、`--target` は指定した構成を記載順で返し、未知の名前は拒否する。"""
    targets = [_target(name="a"), _target(name="b"), _target(name="c")]
    assert target.select_targets(targets, [], True) == targets
    assert [item.name for item in target.select_targets(targets, ["c", "a"], False)] == ["a", "c"]
    with pytest.raises(ValueError, match="設定ファイルに無い"):
        target.select_targets(targets, ["x"], False)


@pytest.mark.parametrize(
    ("relative", "allowed"),
    [
        ("data/output", False),
        ("data/output/limited/run", False),
        ("data/output_other", True),
        ("work", True),
    ],
    ids=["output_root", "inside_output", "similar_name", "outside"],
)
def test_validate_work_dir(tmp_path: Path, relative: str, allowed: bool) -> None:
    """作業先が data/output/ と同じか内側なら拒否する。"""
    work_dir = tmp_path / relative
    if allowed:
        target.validate_work_dir(work_dir, tmp_path)
    else:
        with pytest.raises(ValueError, match="data/output"):
            target.validate_work_dir(work_dir, tmp_path)


def test_shipped_config_is_valid() -> None:
    """リポジトリの設定ファイルが読み込め、保存済み結果が存在する。"""
    targets = target.load_targets(REPO_ROOT / "scripts" / "reproducibility_targets.json")
    assert targets
    for item in targets:
        assert (REPO_ROOT / item.reference_results).is_file()


# --- 再実行（ダミーモジュールをサブプロセスで実行） ---


def test_run_target_match(project: Path, tmp_path: Path) -> None:
    """再実行結果が保存済み結果と一致すれば一致とし、所要時間とライブラリ版の差を記録する。"""
    report = target.run_target(_target(), tmp_path / "work", project, 120)
    assert report.status == target.STATUS_MATCH, report.error
    assert report.compared_count == 4
    assert report.elapsed_seconds is not None and report.elapsed_seconds >= 0
    assert report.package_differences == {"numpy": {"reference": "1.26.4", "rerun": "2.0.0"}}
    assert "fake analysis running" in Path(report.log_path).read_text(encoding="utf-8")


def test_run_target_mismatch(project: Path, tmp_path: Path) -> None:
    """値が許容誤差を超えて違えば不一致とし、キーと値を残す。"""
    report = target.run_target(_target(args=("--value", "0.6")), tmp_path / "work", project, 120)
    assert report.status == target.STATUS_MISMATCH
    assert report.mismatches == [
        {
            "key": "random_split.linear_regression.metrics.r2",
            "reference": 0.5,
            "rerun": 0.6,
            "reason": "値が違う",
        }
    ]


def test_run_target_failure_includes_log_tail(project: Path, tmp_path: Path) -> None:
    """再実行が異常終了すれば実行失敗とし、ログ末尾を説明に含める。"""
    report = target.run_target(_target(args=("--fail",)), tmp_path / "work", project, 120)
    assert report.status == target.STATUS_ERROR
    assert "終了コード 3" in report.error
    assert "boom" in report.error


def test_run_target_missing_reference(project: Path, tmp_path: Path) -> None:
    """保存済み結果が無ければ、再実行せずに実行失敗とする。"""
    calls: list[object] = []

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    report = target.run_target(
        _target(reference_results="data/output/none.json"), tmp_path / "work", project, 120, runner
    )
    assert report.status == target.STATUS_ERROR
    assert "保存済み結果を読めない" in report.error
    assert calls == []


def test_run_target_timeout(project: Path, tmp_path: Path) -> None:
    """待ち時間の上限を超えれば実行失敗とする。"""

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    report = target.run_target(_target(), tmp_path / "work", project, 5, runner)
    assert report.status == target.STATUS_ERROR
    assert "5 秒" in report.error


def test_run_target_requires_single_result(project: Path, tmp_path: Path) -> None:
    """再実行の結果 JSON がちょうど1件でなければ実行失敗とする。"""

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, 0)

    report = target.run_target(_target(), tmp_path / "work", project, 120, runner)
    assert report.status == target.STATUS_ERROR
    assert "0 件" in report.error


def test_build_command_appends_output_dir(tmp_path: Path) -> None:
    """現在の Python で `-m` 実行し、出力先を末尾に付ける。"""
    command = target.build_command(_target(args=("--value", "1")), tmp_path)
    assert command == [
        sys.executable,
        "-m",
        "fake_pkg.fake_analysis",
        "--value",
        "1",
        "--output-dir",
        str(tmp_path),
    ]


# --- 出力・CLI ---


def test_markdown_report_and_exit_code() -> None:
    """Markdown に構成ごとの判定と不一致を載せ、実行失敗を不一致より優先して終了コードを決める。"""
    matched = target.TargetReport(name="a", module="m", status=target.STATUS_MATCH)
    matched.elapsed_seconds = 1.5
    matched.package_differences = {}
    mismatched = target.TargetReport(name="b", module="m", status=target.STATUS_MISMATCH)
    mismatched.mismatches = [{"key": "k", "reference": 1, "rerun": 2, "reason": "値が違う"}]
    failed = target.TargetReport(name="c", module="m", error="起動できない")
    markdown = target.format_markdown_report(
        [matched, mismatched, failed], target.dt.datetime(2026, 10, 21)
    )
    assert "| a | 一致 | 0 | 0 | 1.5 秒 |" in markdown
    assert "| `k` | 1 | 2 | 値が違う |" in markdown
    assert "比較不能" in markdown
    assert "起動できない" in markdown
    assert target.decide_exit_code([matched]) == target.EXIT_ALL_MATCH
    assert target.decide_exit_code([matched, mismatched]) == target.EXIT_MISMATCH
    assert target.decide_exit_code([mismatched, failed]) == target.EXIT_FAILURE


def test_main_runs_target_and_cleans_temp_dir(
    project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """main は構成を再実行して結果を書き出し、自分で作った一時ディレクトリを削除する。"""
    config = _write_config(project, [_config_entry()])
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    monkeypatch.setattr(target, "PROJECT_ROOT", project)
    monkeypatch.setattr(target.tempfile, "tempdir", str(temp_root))
    exit_code = target.main(
        ["--all", "--config", str(config), "--output-json", "out/r.json", "--output-md", "out/r.md"]
    )
    assert exit_code == target.EXIT_ALL_MATCH
    data = json.loads((project / "out" / "r.json").read_text(encoding="utf-8"))
    assert data["targets"][0]["status"] == target.STATUS_MATCH
    assert data["targets"][0]["log_path"] is None
    assert list(temp_root.iterdir()) == []
    assert "| fake | 一致 |" in (project / "out" / "r.md").read_text(encoding="utf-8")


def test_main_keeps_given_work_dir(
    project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--work-dir` を指定した場合は出力を残し、不一致なら終了コード2を返す。"""
    config = _write_config(project, [_config_entry(args=["--value", "0.9"])])
    work_dir = tmp_path / "work"
    monkeypatch.setattr(target, "PROJECT_ROOT", project)
    exit_code = target.main(
        [
            "--target",
            "fake",
            "--config",
            str(config),
            "--work-dir",
            str(work_dir),
            "--output-md",
            "out/r.md",
        ]
    )
    assert exit_code == target.EXIT_MISMATCH
    assert (work_dir / "fake" / "fake_results.json").is_file()
    assert (work_dir / "fake.log").is_file()


def test_main_refuses_work_dir_inside_data_output(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """作業先が data/output/ の内側なら、再実行せずに終了コード1で止める。"""
    config = _write_config(project, [_config_entry()])
    monkeypatch.setattr(target, "PROJECT_ROOT", project)
    exit_code = target.main(["--all", "--config", str(config), "--work-dir", "data/output/rerun"])
    assert exit_code == target.EXIT_FAILURE
    assert not (project / "data" / "output" / "rerun").exists()
    assert "data/output" in capsys.readouterr().err


def test_main_requires_target_selection() -> None:
    """`--target` も `--all` も無ければ引数エラーにする。"""
    with pytest.raises(SystemExit):
        target.main([])
