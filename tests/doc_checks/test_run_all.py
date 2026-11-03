"""run_all.py（ドキュメント整合性チェックの一括実行）のテスト。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.doc_checks.run_all import main

_README_TEMPLATE = """# 📚 研究ドキュメント管理

## 🗂️ ディレクトリ構造

```text
docs/
```

## 📊 全ドキュメントカタログ

| ファイル名 | 概要 |
|---|---|
| [README.md](README.md) | このファイル |
| [01_metadata/papers_database.csv](04_archive/01_metadata/papers_database.csv) | 論文メタデータ |

## 🔄 ドキュメント関係図

本文
"""

_CSV_HEADER = "ID,著者,年\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_valid_project(tmp_path: Path) -> None:
    """全チェックが通過する最小構成のdocs/を用意する。"""
    _write(tmp_path / "docs" / "README.md", _README_TEMPLATE)
    _write(tmp_path / "docs" / "04_archive" / "01_metadata" / "papers_database.csv", _CSV_HEADER)


def test_returns_zero_when_no_violations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """違反がなければ終了コード0を返す。"""
    _build_valid_project(tmp_path)

    exit_code = main(project_root=tmp_path)

    assert exit_code == 0
    assert "[OK]" in capsys.readouterr().out


def test_returns_one_when_broken_link_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """機械的チェックの違反（リンク切れ）があれば終了コード1を返す。"""
    _build_valid_project(tmp_path)
    _write(tmp_path / "docs" / "orphan.md", "[存在しない](missing.md)")
    # orphan.md自体もカタログ未掲載になるため、カタログにも追記して
    # リンク切れ単体の影響を検証する
    readme_path = tmp_path / "docs" / "README.md"
    readme_path.write_text(
        _README_TEMPLATE.replace(
            "| [README.md](README.md) | このファイル |",
            "| [README.md](README.md) | このファイル |\n| [orphan.md](orphan.md) | テスト |",
        ),
        encoding="utf-8",
    )

    exit_code = main(project_root=tmp_path)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "[NG] リンク切れ" in output


def test_freshness_warning_does_not_affect_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """鮮度警告のみの場合は終了コード0のまま（gitリポジトリでないため警告も出ない）。"""
    _build_valid_project(tmp_path)

    exit_code = main(project_root=tmp_path)

    assert exit_code == 0
    assert "[WARN]" not in capsys.readouterr().out


def _git(args: list[str], cwd: Path) -> None:
    """git を実行する。"""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_thesis_tracking_git_failure_is_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """論文の追従チェックが git の失敗で検査できなくても、警告にとどめ終了コード0のまま。"""
    # 親ディレクトリの git リポジトリや GIT_DIR を git に探させない（git 失敗の前提を固定）
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    _build_valid_project(tmp_path)
    _write(
        tmp_path / "thesis" / "chapters" / "01_intro" / "01_background.md",
        "<!--\n状態: 執筆中\n依拠する正本:\n  - docs/README.md @ 0123456789\n-->\n",
    )

    exit_code = main(project_root=tmp_path)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[WARN] 論文の追従（fail対象外）: 検査できませんでした" in output
    assert "[OK] 機械的チェックはすべて通過しました。" in output


def test_thesis_tracking_warning_does_not_affect_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """論文の追従の警告（依拠する正本の更新）は表示するが、終了コード0のまま。"""
    _build_valid_project(tmp_path)
    _write(
        tmp_path / "thesis" / "chapters" / "01_intro" / "01_background.md",
        "<!--\n状態: 執筆中\n依拠する正本:\n  - docs/README.md @ 0123456789\n-->\n",
    )
    _git(["init", "-q"], tmp_path)
    _git(["config", "user.email", "test@example.com"], tmp_path)
    _git(["config", "user.name", "Test"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "test commit"], tmp_path)

    exit_code = main(project_root=tmp_path)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[WARN] 論文の追従" in output
    assert "thesis/chapters/01_intro/01_background.md:4 [正本が更新された] docs/README.md" in output
