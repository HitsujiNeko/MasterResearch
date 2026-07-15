"""run_all.py（ドキュメント整合性チェックの一括実行）のテスト。"""

from __future__ import annotations

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
