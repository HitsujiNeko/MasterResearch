"""scripts/check_external_deps.py（外部依存のヘルスチェック）のテスト。

秘密情報を扱うため、実際の `.env` には触れず `tmp_path` 上のファイルだけを対象とする。
外部コマンド（GEE の初期化・gdalsrsinfo・ruff）は実行関数を差し替えて検証する。
対象は ``src`` パッケージ外のスクリプトのため、``tests/scripts`` との import 名の衝突を
避けるよう、ファイルパスを指定して読み込む。
"""

from __future__ import annotations

import base64
import datetime as dt
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_external_deps.py"


def _load_target() -> ModuleType:
    """対象スクリプトをモジュールとして読み込む。"""
    spec = importlib.util.spec_from_file_location("check_external_deps", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


target = _load_target()

NOW = dt.datetime(2026, 10, 1, 0, 0, tzinfo=dt.timezone.utc)


def _make_jwt(payload: dict[str, object]) -> str:
    """署名部をダミーにした JWT を作る（ペイロードの読み取りだけを試すため）。"""

    def encode(data: dict[str, object]) -> str:
        raw = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode({'alg': 'RS256', 'typ': 'JWT'})}.{encode(payload)}.c2lnbmF0dXJl"


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """差し替え用の実行結果を作る。"""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestDecodeJwtExpiry:
    """decode_jwt_expiry のテスト。"""

    def test_reads_exp_claim(self) -> None:
        """ペイロードの exp を UTC の日時として読む。"""
        expiry = NOW + dt.timedelta(days=10)
        token = _make_jwt({"exp": int(expiry.timestamp())})

        assert target.decode_jwt_expiry(token) == expiry

    @pytest.mark.parametrize(
        "token",
        ["not-a-jwt", "a.b", "a.!!!.c", _make_jwt({"sub": "user"}), _make_jwt({"exp": "soon"})],
    )
    def test_returns_none_when_expiry_is_unreadable(self, token: str) -> None:
        """JWT でない・exp が無い・exp が数値でない場合は None を返す。"""
        assert target.decode_jwt_expiry(token) is None

    def test_rejects_boolean_exp(self) -> None:
        """bool は int の派生型だが、有効期限としては扱わない。"""
        assert target.decode_jwt_expiry(_make_jwt({"exp": True})) is None


class TestJudgeTokenExpiry:
    """judge_token_expiry のテスト（境界値を含む）。"""

    def test_expired_token_is_fail(self) -> None:
        """期限を過ぎていれば FAIL。"""
        result = target.judge_token_expiry(NOW - dt.timedelta(seconds=1), NOW, 45, has_token=True)
        assert result.status == target.STATUS_FAIL

    def test_expiry_at_now_is_fail(self) -> None:
        """残り0秒（ちょうど期限）は失効扱いにする。"""
        result = target.judge_token_expiry(NOW, NOW, 45, has_token=True)
        assert result.status == target.STATUS_FAIL

    def test_expiry_within_warn_days_is_warn(self) -> None:
        """残り日数が閾値未満なら WARN。"""
        result = target.judge_token_expiry(NOW + dt.timedelta(days=44), NOW, 45, has_token=True)
        assert result.status == target.STATUS_WARN
        assert "残り 44 日" in result.message

    def test_expiry_at_warn_days_is_ok(self) -> None:
        """残りがちょうど閾値の日数なら OK（閾値未満のみ通知する）。"""
        result = target.judge_token_expiry(NOW + dt.timedelta(days=45), NOW, 45, has_token=True)
        assert result.status == target.STATUS_OK

    def test_missing_token_is_unknown(self) -> None:
        """トークン未設定は UNKNOWN（判定できない）。"""
        result = target.judge_token_expiry(None, NOW, 45, has_token=False)
        assert result.status == target.STATUS_UNKNOWN

    def test_unreadable_expiry_is_unknown(self) -> None:
        """有効期限を読めないトークンは UNKNOWN。"""
        result = target.judge_token_expiry(None, NOW, 45, has_token=True)
        assert result.status == target.STATUS_UNKNOWN


class TestCheckEarthdataToken:
    """check_earthdata_token のテスト（秘密情報を出さないこと）。"""

    def test_reads_token_from_env_file_without_leaking_value(self, tmp_path: Path) -> None:
        """.env のトークンを判定し、結果の文言にトークンの値を含めない。"""
        token = _make_jwt({"exp": int((NOW + dt.timedelta(days=3)).timestamp())})
        env_path = tmp_path / ".env"
        env_path.write_text(f"EARTHDATA_TOKEN={token}\n", encoding="utf-8")

        result = target.check_earthdata_token({}, env_path, NOW, 45)

        assert result.status == target.STATUS_WARN
        for part in token.split("."):
            assert part not in result.message

    def test_environment_variable_takes_precedence(self, tmp_path: Path) -> None:
        """環境変数のトークンが .env より優先される。"""
        expired = _make_jwt({"exp": int((NOW - dt.timedelta(days=1)).timestamp())})
        valid = _make_jwt({"exp": int((NOW + dt.timedelta(days=100)).timestamp())})
        env_path = tmp_path / ".env"
        env_path.write_text(f"EARTHDATA_TOKEN={expired}\n", encoding="utf-8")

        result = target.check_earthdata_token({"EARTHDATA_TOKEN": valid}, env_path, NOW, 45)

        assert result.status == target.STATUS_OK

    def test_report_does_not_contain_token(self, tmp_path: Path) -> None:
        """報告文全体にもトークンの値が現れない。"""
        token = _make_jwt({"exp": int((NOW - dt.timedelta(days=1)).timestamp())})
        env_path = tmp_path / ".env"
        env_path.write_text(f"EARTHDATA_TOKEN={token}\n", encoding="utf-8")

        report = target.format_report([target.check_earthdata_token({}, env_path, NOW, 45)], NOW)

        assert token not in report
        assert token.split(".")[1] not in report


class TestCheckGee:
    """judge_gee_probe・check_gee のテスト。"""

    def test_success_is_ok(self) -> None:
        """終了コード0なら OK。"""
        assert target.judge_gee_probe(0, "", timed_out=False).status == target.STATUS_OK

    def test_failure_is_fail_with_last_error_line(self) -> None:
        """失敗時は FAIL とし、エラー出力の最後の行だけを要約として出す。"""
        stderr = "Traceback (most recent call last):\n  ...\nee.EEException: Please authorize\n"
        result = target.judge_gee_probe(1, stderr, timed_out=False)

        assert result.status == target.STATUS_FAIL
        assert "ee.EEException: Please authorize" in result.message
        assert "Traceback" not in result.message

    def test_timeout_is_unknown(self) -> None:
        """タイムアウトは UNKNOWN。"""
        assert target.judge_gee_probe(None, "", timed_out=True).status == target.STATUS_UNKNOWN

    def test_does_not_call_authenticate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """子プロセスには Initialize のみを渡し、ブラウザ認証（Authenticate）は呼ばない。"""
        monkeypatch.setattr(target, "resolve_gee_project_id", lambda explicit, path: "demo-project")
        calls: list[list[str]] = []

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            calls.append(command)
            return _completed(0, stdout="ok\n")

        result = target.check_gee("", Path("unused.csv"), "python", runner=fake_runner)

        assert result.status == target.STATUS_OK
        assert len(calls) == 1
        assert "ee.Initialize" in calls[0][2]
        assert "Authenticate" not in calls[0][2]
        assert calls[0][-1] == "demo-project"

    def test_timeout_from_runner_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """実行関数がタイムアウトを送出したら UNKNOWN。"""
        monkeypatch.setattr(target, "resolve_gee_project_id", lambda explicit, path: "demo-project")

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            raise subprocess.TimeoutExpired(command, 1)

        result = target.check_gee("", Path("unused.csv"), "python", runner=fake_runner)

        assert result.status == target.STATUS_UNKNOWN

    def test_launch_failure_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Python を起動できなければ例外で落ちずに UNKNOWN。"""
        monkeypatch.setattr(target, "resolve_gee_project_id", lambda explicit, path: "demo-project")

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            raise OSError("起動できない")

        result = target.check_gee("", Path("unused.csv"), "python", runner=fake_runner)

        assert result.status == target.STATUS_UNKNOWN

    def test_missing_earthengine_api_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """earthengine-api を読み込めなければ UNKNOWN。"""

        def raise_import_error(explicit: str, path: Path) -> str:
            raise ImportError("No module named 'ee'")

        monkeypatch.setattr(target, "resolve_gee_project_id", raise_import_error)

        result = target.check_gee("", Path("unused.csv"), "python")

        assert result.status == target.STATUS_UNKNOWN
        assert "earthengine-api" in result.message

    def test_missing_project_id_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """プロジェクト ID を解決できなければ子プロセスを起動せず UNKNOWN。"""

        def raise_missing(explicit: str, path: Path) -> str:
            raise FileNotFoundError("GEE設定CSVが見つかりません")

        monkeypatch.setattr(target, "resolve_gee_project_id", raise_missing)

        def fail_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            raise AssertionError("起動してはいけない")

        result = target.check_gee("", Path("absent.csv"), "python", runner=fail_runner)

        assert result.status == target.STATUS_UNKNOWN


def _make_osgeo4w(root: Path, layout_minor: str = "2") -> Path:
    """gdalsrsinfo.exe（空ファイル）と proj.db を持つ OSGeo4W 風のディレクトリを作る。"""
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "gdalsrsinfo.exe").write_bytes(b"")
    proj_dir = root / "share" / "proj"
    proj_dir.mkdir(parents=True)
    with sqlite3.connect(proj_dir / "proj.db") as connection:
        connection.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
        connection.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [("PROJ.VERSION", "8.2.1"), ("DATABASE.LAYOUT.VERSION.MINOR", layout_minor)],
        )
    return root


class TestCheckProjDb:
    """OSGeo4W の proj.db 判定のテスト。"""

    def test_find_root_prefers_explicit_then_environment(self, tmp_path: Path) -> None:
        """明示指定 → 環境変数 → 探索候補の順で決める。"""
        explicit = _make_osgeo4w(tmp_path / "explicit")
        from_env = _make_osgeo4w(tmp_path / "env")
        fallback = _make_osgeo4w(tmp_path / "fallback")
        environment = {"OSGEO4W_ROOT": str(from_env)}

        assert target.find_osgeo4w_root(str(explicit), environment, (fallback,)) == explicit
        assert target.find_osgeo4w_root("", environment, (fallback,)) == from_env
        assert target.find_osgeo4w_root("", {}, (fallback,)) == fallback
        assert target.find_osgeo4w_root("", {}, (tmp_path / "absent",)) is None

    def test_isolated_environment_drops_proj_settings(self, tmp_path: Path) -> None:
        """PROJ_LIB 等を取り除き、PATH を OSGeo4W の bin から始める。"""
        environment = {
            "PROJ_LIB": "conda/share/proj",
            "proj_data": "conda/share/proj",
            "GDAL_DATA": "conda/share/gdal",
            "Path": "conda/Library/bin",
            "SystemRoot": "C:/Windows",
            "USERPROFILE": "home",
        }

        isolated = target.build_isolated_environment(tmp_path, environment)

        assert {"PROJ_LIB", "proj_data", "GDAL_DATA", "Path"}.isdisjoint(isolated)
        assert isolated["PATH"].startswith(str(tmp_path / "bin"))
        assert "conda" not in isolated["PATH"]
        assert isolated["USERPROFILE"] == "home"

    def test_layout_version_error_is_fail(self, tmp_path: Path) -> None:
        """既知の版不整合のエラーが出たら FAIL とし、proj.db の版を補足表示する。"""
        root = _make_osgeo4w(tmp_path / "osgeo4w")
        stderr = (
            "ERROR 1: PROJ: proj_create_from_database: proj.db contains "
            "DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 4 is expected.\n"
        )

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            return _completed(1, stderr=stderr)

        result = target.check_proj_db(str(root), {}, runner=fake_runner, candidates=())

        assert result.status == target.STATUS_FAIL
        assert "DATABASE.LAYOUT.VERSION.MINOR=2" in result.message
        assert "PROJ.VERSION=8.2.1" in result.message

    def test_success_is_ok(self, tmp_path: Path) -> None:
        """EPSG:4326 を解決できれば OK。"""
        root = _make_osgeo4w(tmp_path / "osgeo4w", layout_minor="5")

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            assert command[1:] == ["EPSG:4326", "-o", "proj4"]
            return _completed(0, stdout="+proj=longlat +datum=WGS84 +no_defs\n")

        result = target.check_proj_db(str(root), {}, runner=fake_runner, candidates=())

        assert result.status == target.STATUS_OK

    def test_other_failure_is_fail(self) -> None:
        """版不整合以外の失敗も FAIL。"""
        result = target.judge_proj_db(1, "ERROR 1: something else\n", {})
        assert result.status == target.STATUS_FAIL

    def test_launch_failure_is_unknown(self, tmp_path: Path) -> None:
        """ツールを起動できなければ UNKNOWN。"""
        root = _make_osgeo4w(tmp_path / "osgeo4w")

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            raise OSError("起動できない")

        result = target.check_proj_db(str(root), {}, runner=fake_runner, candidates=())

        assert result.status == target.STATUS_UNKNOWN

    def test_missing_installation_is_unknown(self, tmp_path: Path) -> None:
        """OSGeo4W が見つからなければ UNKNOWN。"""
        result = target.check_proj_db("", {}, candidates=(tmp_path / "absent",))
        assert result.status == target.STATUS_UNKNOWN

    def test_metadata_of_absent_db_is_empty(self, tmp_path: Path) -> None:
        """proj.db が無ければ空の辞書を返す。"""
        assert target.read_proj_db_metadata(tmp_path / "absent.db") == {}


class TestRuffVersions:
    """ruff の版の読み取りと判定のテスト。"""

    def test_parses_pins_from_each_file_format(self) -> None:
        """ci.yml・environment.yml・pre-commit・ruff --version の各書式から版を読む。"""
        ci_text = "      - run: pip install ruff==0.16.0\n      - run: ruff check .\n"
        env_text = "dependencies:\n  - python=3.11\n  - ruff=0.16.0\n"
        pre_commit_text = (
            "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.16.0\n"
        )

        assert target.parse_pinned_version(ci_text, target.CI_RUFF_PATTERN) == "0.16.0"
        assert target.parse_pinned_version(env_text, target.ENVIRONMENT_RUFF_PATTERN) == "0.16.0"
        assert (
            target.parse_pinned_version(pre_commit_text, target.PRE_COMMIT_RUFF_PATTERN) == "0.16.0"
        )
        assert target.parse_pinned_version("ruff 0.15.17\n", target.LOCAL_RUFF_PATTERN) == "0.15.17"
        assert target.parse_pinned_version("", target.CI_RUFF_PATTERN) is None

    def test_matching_versions_are_ok(self) -> None:
        """すべて一致すれば OK。"""
        result = target.judge_ruff_versions("0.16.0", "0.16.0", {"environment.yml": "0.16.0"})
        assert result.status == target.STATUS_OK

    def test_local_mismatch_is_warn(self) -> None:
        """ローカル版が CI と違えば WARN とし、両方の版を示す。"""
        result = target.judge_ruff_versions("0.16.0", "0.15.17", {"environment.yml": "0.16.0"})

        assert result.status == target.STATUS_WARN
        assert "0.16.0" in result.message
        assert "ローカル 0.15.17" in result.message
        assert "environment.yml" not in result.message

    def test_other_pin_mismatch_is_warn(self) -> None:
        """他の固定箇所が CI と違っても WARN。見つからない固定箇所は無視する。"""
        result = target.judge_ruff_versions(
            "0.16.0", "0.16.0", {"environment.yml": "0.15.0", ".pre-commit-config.yaml": None}
        )

        assert result.status == target.STATUS_WARN
        assert "environment.yml 0.15.0" in result.message

    def test_unreadable_versions_are_unknown(self) -> None:
        """CI 固定版やローカル版を取得できなければ UNKNOWN。"""
        assert target.judge_ruff_versions(None, "0.16.0", {}).status == target.STATUS_UNKNOWN
        assert target.judge_ruff_versions("0.16.0", None, {}).status == target.STATUS_UNKNOWN

    def test_check_ruff_reads_files_and_runner(self, tmp_path: Path) -> None:
        """設定ファイルと ruff --version の結果を集めて判定する。"""
        ci_path = tmp_path / "ci.yml"
        ci_path.write_text("- run: pip install ruff==0.16.0\n", encoding="utf-8")

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            assert command[1:] == ["-m", "ruff", "--version"]
            return _completed(0, stdout="ruff 0.15.17\n")

        result = target.check_ruff(
            "python",
            runner=fake_runner,
            ci_workflow_path=ci_path,
            environment_yml_path=tmp_path / "absent.yml",
            pre_commit_config_path=tmp_path / "absent.yaml",
        )

        assert result.status == target.STATUS_WARN

    def test_failed_version_command_gives_none(self) -> None:
        """ruff --version が失敗したら None を返す。"""

        def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            return _completed(1, stderr="No module named ruff\n")

        assert target.get_local_ruff_version("python", runner=fake_runner) is None

    def test_repository_pins_are_consistent(self) -> None:
        """リポジトリ内の固定箇所（CI・environment.yml・pre-commit）は互いに一致している。"""
        ci_version = target.parse_pinned_version(
            target.read_text_if_exists(target.CI_WORKFLOW_PATH), target.CI_RUFF_PATTERN
        )
        environment_version = target.parse_pinned_version(
            target.read_text_if_exists(target.ENVIRONMENT_YML_PATH),
            target.ENVIRONMENT_RUFF_PATTERN,
        )
        pre_commit_version = target.parse_pinned_version(
            target.read_text_if_exists(target.PRE_COMMIT_CONFIG_PATH),
            target.PRE_COMMIT_RUFF_PATTERN,
        )

        assert ci_version is not None
        assert environment_version == ci_version
        assert pre_commit_version == ci_version


class TestFormatReport:
    """format_report のテスト。"""

    def test_all_ok_gives_single_line(self) -> None:
        """全項目 OK なら1行の「問題なし」だけを出す。"""
        results = [target.CheckResult("A", target.STATUS_OK, "詳細A")]

        report = target.format_report(results, NOW)

        assert report.count("\n") == 0
        assert "問題なし" in report
        assert "詳細A" not in report

    def test_only_problems_are_listed_in_severity_order(self) -> None:
        """OK 以外の項目だけを、FAIL → WARN → UNKNOWN の順に並べる。"""
        results = [
            target.CheckResult("ok", target.STATUS_OK, "表示しない"),
            target.CheckResult("unknown", target.STATUS_UNKNOWN, "u"),
            target.CheckResult("warn", target.STATUS_WARN, "w"),
            target.CheckResult("fail", target.STATUS_FAIL, "f"),
        ]

        report = target.format_report(results, NOW)

        assert "表示しない" not in report
        assert "要対応 3 件 / 4 項目" in report
        assert report.index("[FAIL]") < report.index("[WARN]") < report.index("[UNKNOWN]")


class TestMain:
    """main の終了コードのテスト。"""

    def _patch_checks(self, monkeypatch: pytest.MonkeyPatch, status: str) -> None:
        """各項目の判定を固定の結果に差し替える。"""
        fixed = target.CheckResult("x", status, "m")
        monkeypatch.setattr(target, "check_earthdata_token", lambda *args: fixed)
        monkeypatch.setattr(target, "check_gee", lambda *args: fixed)
        monkeypatch.setattr(target, "check_proj_db", lambda *args: fixed)
        monkeypatch.setattr(target, "check_ruff", lambda *args: fixed)

    def test_returns_zero_when_all_ok(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """全項目 OK なら 0 を返す。"""
        self._patch_checks(monkeypatch, target.STATUS_OK)

        assert target.main([]) == 0
        assert "問題なし" in capsys.readouterr().out

    def test_passes_cli_options_to_checks(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLI 引数が各判定関数へ正しく渡る。"""
        received: dict[str, tuple[object, ...]] = {}
        fixed = target.CheckResult("x", target.STATUS_OK, "m")

        def recorder(name: str):
            def record(*args: object) -> target.CheckResult:
                received[name] = args
                return fixed

            return record

        for name in ("check_earthdata_token", "check_gee", "check_proj_db", "check_ruff"):
            monkeypatch.setattr(target, name, recorder(name))
        env_path = tmp_path / "custom.env"
        gee_config = tmp_path / "gee.csv"

        code = target.main(
            [
                "--env-file",
                str(env_path),
                "--warn-days",
                "10",
                "--gee-project-id",
                "demo-project",
                "--gee-config",
                str(gee_config),
                "--osgeo4w-root",
                "D:/OSGeo4W",
            ]
        )

        assert code == 0
        assert received["check_earthdata_token"][1] == env_path
        assert received["check_earthdata_token"][3] == 10
        assert received["check_gee"][:2] == ("demo-project", gee_config)
        assert received["check_proj_db"][0] == "D:/OSGeo4W"

    @pytest.mark.parametrize("warn_days", ["-1", "x"])
    def test_rejects_invalid_warn_days(self, warn_days: str) -> None:
        """--warn-days は 0 以上の整数のみ受け付ける。"""
        with pytest.raises(SystemExit):
            target.main(["--warn-days", warn_days])

    def test_unexpected_exception_becomes_unknown_with_type_name_only(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """1項目で予期しない例外が出ても他の項目は報告され、例外の本文は出さない。"""
        self._patch_checks(monkeypatch, target.STATUS_OK)

        def broken(*args: object) -> target.CheckResult:
            raise PermissionError("secret-token-value を含むメッセージ")

        monkeypatch.setattr(target, "check_proj_db", broken)

        code = target.main(["--skip-gee"])

        out = capsys.readouterr().out
        assert code == 1
        assert "要対応 1 件 / 3 項目" in out
        assert (
            f"[UNKNOWN] {target.CHECK_NAME_PROJ_DB}: "
            "判定中に予期しない例外が発生しました（PermissionError）"
        ) in out
        assert "secret-token-value" not in out

    def test_utf16_env_file_is_reported_as_unknown(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """UTF-16 の .env でも全体は落ちず、Earthdata の項目だけが UNKNOWN になる。"""
        fixed = target.CheckResult("x", target.STATUS_OK, "m")
        monkeypatch.setattr(target, "check_proj_db", lambda *args: fixed)
        monkeypatch.setattr(target, "check_ruff", lambda *args: fixed)
        monkeypatch.delenv(target.EARTHDATA_TOKEN_ENV_VAR, raising=False)
        env_path = tmp_path / "utf16.env"
        env_path.write_text(f"{target.EARTHDATA_TOKEN_ENV_VAR}=secret-token-value\n", "utf-16")

        code = target.main(["--skip-gee", "--env-file", str(env_path)])

        out = capsys.readouterr().out
        assert code == 1
        assert f"[UNKNOWN] {target.CHECK_NAME_EARTHDATA}: " in out
        assert "UnicodeDecodeError" in out
        assert "secret-token-value" not in out

    def test_returns_one_when_problem_exists(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """問題のある項目があれば 1 を返す。"""
        self._patch_checks(monkeypatch, target.STATUS_WARN)

        assert target.main(["--skip-gee"]) == 1
        assert "要対応 3 件 / 3 項目" in capsys.readouterr().out
