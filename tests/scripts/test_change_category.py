"""scripts/change_category.py（差分パスによる変更区分の判定）のテスト。

対象は ``src`` パッケージ外のスクリプトのため、import 名の衝突と ``PYTHONPATH`` の影響を
避けるよう、ファイルパスを指定して読み込む。git を使うテストは一時リポジトリで行う。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "change_category.py"


def _load_target():
    """対象スクリプトをモジュールとして読み込む。"""
    spec = importlib.util.spec_from_file_location("change_category", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


target = _load_target()

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git が必要")


def _sample_path(pattern: str) -> str:
    """規則のパターンに一致する具体的なパスを作る（``*`` を配下のファイルに置き換える）。"""
    return pattern.replace("*", "sub/file.md")


def _git(repo: Path, *args: str) -> None:
    """一時リポジトリで git を実行する（失敗時は例外）。"""
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """main に 1 コミットあり、作業ブランチ feature を切った一時リポジトリ。"""
    # 実行者のグローバル設定（コミット署名・フック等）の影響を受けないよう切り離す
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "src" / "analysis").mkdir(parents=True)
    (repo / "src" / "analysis" / "old.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    _git(repo, "checkout", "-q", "-b", "feature")
    return repo


class TestRules:
    """区分表（RULES）の各規則のテスト。"""

    @pytest.mark.parametrize(
        ("category", "pattern"),
        [(category, pattern) for category, pattern, _ in target.RULES],
    )
    def test_each_rule_classifies_matching_path(self, category: str, pattern: str) -> None:
        """各規則に一致するパスは、その規則の区分と根拠で判定される。"""
        result = target.classify_path(_sample_path(pattern))

        assert result.category == category
        assert result.reason.startswith(f"{pattern}: ")

    def test_r_and_s_rules_do_not_overlap(self) -> None:
        """R の規則に一致するパスが S の規則にも一致しない（区分表に重なりがない）。"""
        for category, pattern, _ in target.RULES:
            sample = _sample_path(pattern)
            other_matches = [
                other_pattern
                for other_category, other_pattern, _ in target.RULES
                if other_category != category and target.fnmatch.fnmatchcase(sample, other_pattern)
            ]
            assert other_matches == [], f"{sample} が {pattern} と {other_matches} に一致"

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("src/analysis/analysis_rq3_limited.py", "R"),
            ("data/output/rq3/results.json", "R"),
            ("docs/02_methods/calc_urban_params_raster.md", "R"),
            ("docs/02_methods/qgis_mcp_usage_guide.md", "S"),
            ("docs/setup.md", "S"),
            ("docs/setup/windows.md", "S"),
            (".markdownlint-cli2.jsonc", "S"),
            (".claude/skills/self-review/SKILL.md", "S"),
            ("tests/analysis/test_x.py", "S"),
        ],
    )
    def test_representative_paths(self, path: str, expected: str) -> None:
        """実在する代表的なパスが旧区分表どおりに判定される。"""
        assert target.classify_path(path).category == expected

    @pytest.mark.parametrize(
        "path",
        [
            "gpkgの確認結果.md",
            "src/__init__.py",
            "src/README.md",
            "src/analysis_x.py",
            "scripts2/tool.py",
            "Scripts/tool.py",
            "claude.md",
            "qgis/templates/layout.qpt",
            "docs/02_methods/新規.md",
            "data/raw/a.tif",
        ],
    )
    def test_unlisted_path_defaults_to_r(self, path: str) -> None:
        """どの規則にも一致しないパス（境界・大文字小文字違いを含む）は既定の R になる。"""
        result = target.classify_path(path)

        assert result.category == "R"
        assert result.reason == target.DEFAULT_REASON

    def test_heavier_rule_wins_when_rules_overlap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """複数の規則に一致した場合は、定義順によらず重い方（R）を採る。"""
        monkeypatch.setattr(
            target,
            "RULES",
            (("S", "a/*", "広い S"), ("R", "a/b/*", "狭い R"), ("S", "a/b/c*", "後の S")),
        )

        result = target.classify_path("a/b/c.py")

        assert result.category == "R"
        assert result.reason == "a/b/*: 狭い R"


class TestNormalizePath:
    """normalize_path のテスト。"""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (".claude\\commands\\create-pr.md", ".claude/commands/create-pr.md"),
            ("./src/analysis/x.py", "src/analysis/x.py"),
            ("././tests/a.py", "tests/a.py"),
            ("  tests/a.py  ", "tests/a.py"),
            ("src/analysis/", "src/analysis/"),
        ],
    )
    def test_normalizes_separator_and_prefix(self, path: str, expected: str) -> None:
        """``\\`` を ``/`` にし、先頭の ``./`` と前後の空白を除く。末尾の ``/`` は残す。"""
        assert target.normalize_path(path) == expected

    @pytest.mark.parametrize(
        "path",
        [
            "/etc/passwd",
            "C:\\MasterResearch\\a.py",
            "c:/x.py",
            "",
            "./",
            "scripts/../src/analysis/x.py",
            "..\\outside.py",
            "tests/..",
        ],
    )
    def test_rejects_invalid_path(self, path: str) -> None:
        """絶対パス・空のパス・``..`` を含むパス（軽い区分に一致しうる）は実行エラーにする。"""
        with pytest.raises(target.ChangeCategoryError):
            target.normalize_path(path)

    @pytest.mark.parametrize(
        ("path", "expected"),
        [("src/analysis/", "R"), (".claude/", "S"), ("scripts/", "S"), ("src/", "R")],
    )
    def test_directory_path_is_classified(self, path: str, expected: str) -> None:
        """末尾 ``/`` のディレクトリ指定も配下の規則で照合できる（上位ディレクトリは既定 R）。"""
        assert target.classify_path(target.normalize_path(path)).category == expected


class TestClassifyPaths:
    """classify_paths・overall_category・format_report のテスト。"""

    def test_orders_r_first_and_removes_duplicates(self) -> None:
        """R を先に並べ、同じ区分内は入力順を保ち、重複（正規化後）を除く。"""
        results = target.classify_paths(
            ["tests/a.py", "src/analysis/x.py", ".\\tests\\a.py", "scripts/b.py", "images/c.png"]
        )

        assert [(r.category, r.path) for r in results] == [
            ("R", "src/analysis/x.py"),
            ("R", "images/c.png"),
            ("S", "tests/a.py"),
            ("S", "scripts/b.py"),
        ]

    def test_overall_is_r_when_mixed(self) -> None:
        """R と S が混在すれば全体は R（テストだけでなく R のコードも変えた場合）。"""
        results = target.classify_paths(["src/analysis/x.py", "tests/analysis/test_x.py"])

        assert target.overall_category(results) == "R"

    def test_overall_is_s_when_all_s(self) -> None:
        """全パスが S なら全体は S。"""
        results = target.classify_paths([".github/task-workflow.md", "tests/a.py"])

        assert target.overall_category(results) == "S"

    def test_report_ends_with_overall_line(self) -> None:
        """1 パス 1 行で区分・パス・根拠を出し、最終行に全体の区分と件数を出す。"""
        lines = target.format_report(target.classify_paths(["tests/a.py", "x.md"]))

        assert lines == [
            "R  x.md  [未列挙（既定 R）]",
            "S  tests/a.py  [tests/*: テストのみの変更]",
            "全体: R（R 1 件 / S 1 件）",
        ]


class TestCheckExpected:
    """check_expected のテスト。"""

    def test_expect_s_with_r_path_returns_1(self) -> None:
        """確定済み S に R のパスがあれば 1 を返し、該当パスを示す。"""
        results = target.classify_paths(["src/analysis/x.py", "tests/a.py"])

        exit_code, messages = target.check_expected(results, "S")

        assert exit_code == 1
        assert "  src/analysis/x.py" in messages
        assert "  tests/a.py" not in messages

    @pytest.mark.parametrize(
        ("paths", "expected"),
        [(["tests/a.py"], "S"), (["src/analysis/x.py"], "R"), (["tests/a.py"], "R")],
    )
    def test_expect_within_range_returns_0(self, paths: list[str], expected: str) -> None:
        """期待した区分以内なら 0。"""
        exit_code, _ = target.check_expected(target.classify_paths(paths), expected)

        assert exit_code == 0

    def test_expect_d_lists_r_paths_and_returns_0(self) -> None:
        """確定済み D は 0 を返し、内容確認が必要な R のパスを列挙する。"""
        results = target.classify_paths(["src/analysis/x.py", "tests/a.py"])

        exit_code, messages = target.check_expected(results, "D")

        assert exit_code == 0
        assert "  src/analysis/x.py" in messages
        assert "  tests/a.py" not in messages

    def test_expect_d_without_r_path(self) -> None:
        """確定済み D で R のパスがなければ、その旨を示して 0 を返す。"""
        exit_code, messages = target.check_expected(target.classify_paths(["tests/a.py"]), "D")

        assert exit_code == 0
        assert "R のパスはありません。" in messages
        assert "S のパスも" in messages[-1]


class TestMainWithPaths:
    """パス指定モードの main のテスト。"""

    def test_prints_report_and_returns_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        """パスを判定して出力し、--expect なしなら 0 を返す。"""
        exit_code = target.main(["src/analysis/x.py", "tests/a.py"])

        out = capsys.readouterr().out
        assert exit_code == 0
        assert out.splitlines()[-1] == "全体: R（R 1 件 / S 1 件）"

    def test_expect_s_with_r_path_returns_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--expect S で R のパスがあれば 1 を返す。"""
        assert target.main(["--expect", "S", "src/analysis/x.py"]) == 1

    def test_paths_with_base_is_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """パス指定と --base の併用は 2 を返し、標準エラーに理由を出す。"""
        exit_code = target.main(["--base", "main", "tests/a.py"])

        assert exit_code == 2
        assert "併用できません" in capsys.readouterr().err

    def test_absolute_path_is_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """絶対パスは 2 を返す。"""
        assert target.main(["C:\\MasterResearch\\a.py"]) == 2

    def test_expect_r_returns_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--expect R は R のパスがあっても 0 を返す。"""
        assert target.main(["--expect", "R", "src/analysis/x.py", "tests/a.py"]) == 0

    def test_unexpected_exception_returns_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """想定外の例外は 2 を返す（区分違反の 1 と取り違えないため）。"""

        def raise_permission_error(*args: object, **kwargs: object) -> None:
            raise PermissionError("拒否")

        monkeypatch.setattr(target.subprocess, "run", raise_permission_error)

        assert target.main(["--expect", "S"]) == 2
        assert "想定外のエラー" in capsys.readouterr().err

    def test_git_not_found_returns_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """git コマンドが見つからない場合は 2 を返す。"""

        def raise_file_not_found(*args: object, **kwargs: object) -> None:
            raise FileNotFoundError("git")

        monkeypatch.setattr(target.subprocess, "run", raise_file_not_found)

        assert target.main([]) == 2
        assert "git コマンドが見つかりません" in capsys.readouterr().err

    def test_invalid_expect_exits_2(self) -> None:
        """--expect に R/S/D 以外を渡すと argparse が終了コード 2 で止める。"""
        with pytest.raises(SystemExit) as excinfo:
            target.main(["--expect", "X", "tests/a.py"])

        assert excinfo.value.code == 2


@requires_git
class TestGitMode:
    """git 差分モードのテスト（一時リポジトリ）。"""

    def test_rename_reports_both_old_and_new_path(self, git_repo: Path) -> None:
        """リネームは元と先の両方のパスを返す（リネーム元の区分を見落とさない）。"""
        (git_repo / "tests").mkdir()
        _git(git_repo, "mv", "src/analysis/old.py", "tests/new.py")
        _git(git_repo, "commit", "-q", "-m", "rename")

        paths = target.get_diff_paths("main", cwd=str(git_repo))

        assert sorted(paths) == ["src/analysis/old.py", "tests/new.py"]

    def test_deleted_file_is_reported(self, git_repo: Path) -> None:
        """削除したファイルのパスも差分に含まれる（削除元の区分を見落とさない）。"""
        _git(git_repo, "rm", "-q", "src/analysis/old.py")
        _git(git_repo, "commit", "-q", "-m", "delete")

        assert target.get_diff_paths("main", cwd=str(git_repo)) == ["src/analysis/old.py"]

    def test_japanese_path_is_not_escaped(self, git_repo: Path) -> None:
        """日本語パスが 8 進エスケープされずにそのまま返る。"""
        (git_repo / "gpkgの確認結果.md").write_text("メモ\n", encoding="utf-8")
        _git(git_repo, "add", ".")
        _git(git_repo, "commit", "-q", "-m", "add japanese")

        assert target.get_diff_paths("main", cwd=str(git_repo)) == ["gpkgの確認結果.md"]

    def test_uncommitted_changes_are_not_included(self, git_repo: Path) -> None:
        """未コミットの変更は判定に含めない（push されるのはコミット済みの差分のみ）。"""
        (git_repo / "tests").mkdir()
        (git_repo / "tests" / "a.py").write_text("x = 1\n", encoding="utf-8")
        _git(git_repo, "add", ".")
        _git(git_repo, "commit", "-q", "-m", "add test")
        (git_repo / "src" / "analysis" / "old.py").write_text("x = 2\n", encoding="utf-8")

        assert target.get_diff_paths("main", cwd=str(git_repo)) == ["tests/a.py"]

    def test_missing_base_raises(self, git_repo: Path) -> None:
        """存在しない比較基準は実行エラーにする。"""
        with pytest.raises(target.ChangeCategoryError, match="no-such-ref"):
            target.get_diff_paths("no-such-ref", cwd=str(git_repo))

    def test_empty_diff_returns_2(
        self,
        git_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """差分 0 件は 2 を返す。"""
        monkeypatch.chdir(git_repo)

        assert target.main(["--base", "main"]) == 2
        assert "差分がありません" in capsys.readouterr().err

    def test_main_judges_diff(
        self,
        git_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """差分パスを判定し、--expect S で S のみなら 0 を返す。"""
        (git_repo / ".github").mkdir()
        (git_repo / ".github" / "a.md").write_text("a\n", encoding="utf-8")
        _git(git_repo, "add", ".")
        _git(git_repo, "commit", "-q", "-m", "add doc")
        monkeypatch.chdir(git_repo)

        exit_code = target.main(["--base", "main", "--expect", "S"])

        assert exit_code == 0
        assert "全体: S（R 0 件 / S 1 件）" in capsys.readouterr().out


class TestCommandLine:
    """スクリプトをサブプロセスとして実行するテスト。"""

    def test_japanese_output_is_utf8(self) -> None:
        """出力エンコーディングの環境変数がなくても、日本語を UTF-8 で出力する。"""
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}

        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "gpkgの確認結果.md"],
            capture_output=True,
            env=env,
            check=False,
        )

        assert completed.returncode == 0
        out = completed.stdout.decode("utf-8")
        assert "R  gpkgの確認結果.md  [未列挙（既定 R）]" in out
        assert "全体: R" in out
