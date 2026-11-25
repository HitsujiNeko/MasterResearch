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
        ({"name": "../escape"}, "name"),
        ({"name": "C:/data/output/x"}, "name"),
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
        "name_with_separator",
        "name_absolute_path",
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


# --- レビューで補った境界・異常系 ---


def test_values_match_treats_both_nan_as_equal() -> None:
    """両方が NaN なら一致とし、片方だけが NaN なら不一致とする。"""
    nan = float("nan")
    assert target.values_match(nan, nan, 1e-9, 1e-6) is True
    assert target.values_match(nan, 0.5, 1e-9, 1e-6) is False
    assert target.values_match(float("inf"), float("inf"), 1e-9, 1e-6) is True


def test_run_target_fails_when_nothing_compared(project: Path, tmp_path: Path) -> None:
    """照合キーがどちらの結果 JSON にも無く照合が0件なら、一致ではなく実行失敗とする。"""
    report = target.run_target(_target(compare_keys=("typo_key",)), tmp_path / "work", project, 120)
    assert report.status == target.STATUS_ERROR
    assert report.compared_count == 0
    assert "0件" in report.error


def test_run_target_refuses_non_empty_output_dir(project: Path, tmp_path: Path) -> None:
    """構成ごとの出力先に前回の出力が残っていれば、消さずに実行失敗とする。"""
    work_dir = tmp_path / "work"
    leftover = work_dir / "fake" / "old_results.json"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("{}", encoding="utf-8")
    calls: list[object] = []

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    report = target.run_target(_target(), work_dir, project, 120, runner)
    assert report.status == target.STATUS_ERROR
    assert "空ではない" in report.error
    assert calls == []
    assert leftover.is_file()


# --- 別の作業ツリーの入力（--data-root・inputs）と来歴の差 ---


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ("data/x.gpkg", "空でない文字列のリスト"),
        ([""], "空でない文字列のリスト"),
        (["C:/data/x.gpkg"], "プロジェクト相対"),
        (["../x.gpkg"], "プロジェクト相対"),
        (["data/y.gpkg"], "`args` にありません"),
        (["data/x.gpkg", "data/x.gpkg"], "重複"),
    ],
    ids=["not_list", "empty", "absolute", "parent", "not_in_args", "duplicate"],
)
def test_parse_target_rejects_invalid_inputs(inputs: object, message: str) -> None:
    """`inputs` の型・絶対パス・`..`・`args` に無い値・重複を拒否する。"""
    entry = _config_entry(args=["--dataset", "data/x.gpkg"], inputs=inputs)
    with pytest.raises(ValueError, match=message):
        target.parse_target(entry, 0)


def test_parse_target_reads_inputs() -> None:
    """`inputs` を読み込み、省略時は空とする。"""
    entry = _config_entry(args=["--dataset", "data/x.gpkg"], inputs=["data/x.gpkg"])
    assert target.parse_target(entry, 0).inputs == ("data/x.gpkg",)
    assert target.parse_target(_config_entry(), 0).inputs == ()


def test_build_command_replaces_inputs(tmp_path: Path) -> None:
    """`args` の値が入力と完全に一致するものだけを置き換える（オプション名などは触らない）。"""
    item = _target(args=("--dataset", "data/x.gpkg", "--note", "data/x.gpkg.bak"))
    resolved = tmp_path / "data" / "x.gpkg"
    command = target.build_command(item, tmp_path / "out", {"data/x.gpkg": resolved})
    assert command[3:7] == ["--dataset", str(resolved), "--note", "data/x.gpkg.bak"]


def test_run_target_reads_inputs_from_data_root(project: Path, tmp_path: Path) -> None:
    """入力は基準ディレクトリの下の絶対パスで渡し、再実行はプロジェクトルートで行う。"""
    data_root = tmp_path / "main_checkout"
    dataset = data_root / "data" / "x.gpkg"
    dataset.parent.mkdir(parents=True)
    dataset.write_bytes(b"gpkg")
    commands: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        commands.append(command)
        assert kwargs["cwd"] == project
        # ダミーの分析は --dataset を受け付けないため、照合に使う結果だけを書き出す
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "fake_results.json").write_text(json.dumps(REFERENCE), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    item = _target(args=("--dataset", "data/x.gpkg"), inputs=("data/x.gpkg",))
    report = target.run_target(item, tmp_path / "work", project, 120, runner, data_root)
    assert report.status == target.STATUS_MATCH, report.error
    assert commands[0][4] == str(dataset.resolve())


def test_run_target_fails_on_missing_input(project: Path, tmp_path: Path) -> None:
    """入力が基準ディレクトリの下に無ければ、再実行せずに入力欠落の実行失敗とする。"""
    calls: list[object] = []

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    item = _target(args=("--dataset", "data/x.gpkg"), inputs=("data/x.gpkg",))
    report = target.run_target(item, tmp_path / "work", project, 120, runner, tmp_path)
    assert report.status == target.STATUS_ERROR
    assert report.error.startswith("入力欠落")
    assert "data/x.gpkg" in report.error
    assert calls == []


def test_validate_work_dir_protects_data_root_output(tmp_path: Path) -> None:
    """入力の基準ディレクトリの data/output/ の内側も出力先として拒否する。"""
    project_root = tmp_path / "worktree"
    data_root = tmp_path / "main"
    target.validate_work_dir(tmp_path / "work", project_root, data_root)
    with pytest.raises(ValueError, match="data/output"):
        target.validate_work_dir(data_root / "data" / "output" / "x", project_root, data_root)


def _provenance(inputs: list[dict[str, str]], files: list[dict[str, str]]) -> dict[str, object]:
    """来歴だけを持つ結果 JSON を作る。"""
    return {"provenance": {"inputs": inputs, "code": {"files": files}}}


def test_compare_inputs_matches_by_file_name() -> None:
    """入力はファイル名で対応付け、記録されたパスの違い（相対・絶対）は差にしない。"""
    reference = _provenance(
        [{"path": "data/x.gpkg", "sha256": "a" * 64}, {"path": "data/c.csv", "sha256": "c"}], []
    )
    rerun = _provenance(
        [
            {"path": "C:/main/data/x.gpkg", "sha256": "a" * 64},
            {"path": "data/c.csv", "sha256": "d"},
        ],
        [],
    )
    assert target.compare_inputs(reference, rerun) == {"c.csv": {"reference": "c", "rerun": "d"}}
    assert target.compare_inputs(reference, {"provenance": {}}) is None
    assert target.compare_inputs({}, rerun) is None


def test_compare_code_lists_changed_added_and_removed_files() -> None:
    """コードのハッシュの変更・追加・削除を差として返し、記録が無ければ比較不能とする。"""
    reference = _provenance(
        [], [{"path": "src/a.py", "sha256": "1"}, {"path": "src/b.py", "sha256": "2"}]
    )
    rerun = _provenance(
        [], [{"path": "src/a.py", "sha256": "1"}, {"path": "src/c.py", "sha256": "3"}]
    )
    assert target.compare_code(reference, rerun) == {
        "src/b.py": {"reference": "2", "rerun": None},
        "src/c.py": {"reference": None, "rerun": "3"},
    }
    assert target.compare_code(reference, reference) == {}
    assert target.compare_code(reference, {"provenance": {"code": {"files": "x"}}}) is None


def test_markdown_report_lists_provenance_differences_and_truncates() -> None:
    """来歴の差（入力・コード）を載せ、多い不一致・差は先頭だけにして件数を添える。"""
    report = target.TargetReport(name="a", module="m", status=target.STATUS_MISMATCH)
    report.mismatches = [
        {"key": f"k{i}", "reference": 1, "rerun": 2, "reason": "値が違う"} for i in range(35)
    ]
    report.package_differences = {}
    report.input_differences = None
    report.code_differences = {
        f"src/f{i}.py": {"reference": "a" * 64, "rerun": None} for i in range(12)
    }
    markdown = target.format_markdown_report([report], target.dt.datetime(2026, 11, 26))
    assert "| `k29` |" in markdown
    assert "| `k30` |" not in markdown
    assert "ほか 5 件" in markdown
    assert "- ライブラリ版の差: なし" in markdown
    assert "- 入力の差（SHA-256）: 比較不能" in markdown
    assert "- コードの差（ファイルハッシュ）: 12 件（src/f0.py aaaaaaaaaaaa → なし" in markdown
    assert "ほか 2 件）" in markdown


def test_main_uses_data_root(
    project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--data-root` の入力を使い、無い基準ディレクトリは開始前に拒否する。"""
    data_root = tmp_path / "main_checkout"
    (data_root / "data").mkdir(parents=True)
    (data_root / "data" / "x.txt").write_text("x", encoding="utf-8")
    config = _write_config(
        project, [_config_entry(args=["--value", "data/x.txt"], inputs=["data/x.txt"])]
    )
    monkeypatch.setattr(target, "PROJECT_ROOT", project)
    base = ["--all", "--config", str(config), "--output-json", "out/r.json"]
    # ダミーの分析は --value を数値として読むため、入力が渡れば引数エラーで実行失敗になる。
    # 入力欠落で止まらずに再実行まで進んだことを、失敗の理由で確かめる
    assert target.main([*base, "--data-root", str(data_root)]) == target.EXIT_FAILURE
    data = json.loads((project / "out" / "r.json").read_text(encoding="utf-8"))
    assert "終了コード" in data["targets"][0]["error"]
    assert data["data_root"] == data_root.resolve().as_posix()
    assert target.main([*base, "--data-root", str(tmp_path / "none")]) == target.EXIT_FAILURE


# --- リポジトリの設定ファイルと保存済み結果の記録の突き合わせ ---

# 引数で明示しなくてよい分析スクリプトのオプション（出力先は本スクリプトが付ける。
# 残りは真偽値のフラグで、保存済み結果の記録と一致することを別に確かめる）
_IMPLICIT_OPTIONS = frozenset({"output_dir", "diagnose_only", "require_valid_gis_mask"})


def _shipped_targets() -> list[object]:
    """リポジトリの設定ファイルの全構成を読み込む。"""
    return target.load_targets(REPO_ROOT / "scripts" / "reproducibility_targets.json")


@pytest.mark.parametrize("item", _shipped_targets(), ids=lambda item: item.name)
def test_shipped_config_matches_recorded_settings(item: object) -> None:
    """各構成の引数を分析スクリプトのパーサで解釈すると、保存済み結果に記録された設定と一致し、
    既定値に頼る引数が無い（既定値を変えても対象構成がずれないようにするため）。"""
    import importlib

    reference = json.loads((REPO_ROOT / item.reference_results).read_text(encoding="utf-8-sig"))
    assert reference["provenance"]["script"] == item.module
    module = importlib.import_module(item.module)
    namespace = module.parse_arguments([*item.args, "--output-dir", "unused"])
    values = vars(namespace)
    evaluation_cells = reference.get("evaluation_cells")
    # 評価セルを使わない通常ランでは、--evaluation-cells を付けないこと自体が設定である
    allowed = _IMPLICIT_OPTIONS if evaluation_cells else _IMPLICIT_OPTIONS | {"evaluation_cells"}
    implicit = sorted(
        f"--{key.replace('_', '-')}"
        for key in values
        if key not in allowed and f"--{key.replace('_', '-')}" not in item.args
    )
    assert implicit == [], f"既定値に頼っている引数: {implicit}"

    run_parameters = reference["run_parameters"]
    args = list(item.args)
    assert args[args.index("--dataset-path") + 1] == reference["dataset_path"]
    assert list(item.inputs) == [reference["dataset_path"]]
    assert values["scale"] == run_parameters["scale_m"]
    assert values["sample_size"] == run_parameters["requested_sample_size"]
    assert values["random_state"] == run_parameters["random_state"]
    assert values["rf_trees"] == run_parameters["rf_trees"]
    assert values["shap_sample_size"] == run_parameters["requested_shap_sample_size"]
    assert values["shap_background_size"] == run_parameters["requested_shap_background_size"]
    assert values["cv_splits"] == reference["spatial_cv"]["cv_splits"]
    assert values["block_size_m"] == reference["spatial_cv"]["block_definition"]["block_size_m"]
    assert values["lst_valid_ratio_threshold"] == reference["lst_valid_ratio_threshold"]
    assert values["analysis_area"] == reference["analysis_area"]
    assert values.get("diagnose_only", False) is False
    if evaluation_cells:
        assert args[args.index("--evaluation-cells") + 1] == evaluation_cells["path"]
        assert "evaluation_cells" in item.compare_keys
    else:
        assert values["evaluation_cells"] is None
    if reference["scenario"] == "Limited":
        assert values["variable_set"] == reference["variable_set"]
        assert values["building_height"] == reference["building_height_mode"]
        assert values["water_index"] == reference["water_index_mode"]
        assert values["population_source"] == reference["population_sources"]
        assert values["require_valid_gis_mask"] == reference["require_valid_gis_mask"]
    # 論文の結論に使う SHAP の順位・母数・実行条件も照合する
    for key in ("shap", "filter_dropout", "run_parameters", *target.DEFAULT_COMPARE_KEYS):
        assert key in item.compare_keys
        assert key in reference
