"""thesis_source_tracking.py（論文の節が依拠する正本の更新検出）のテスト。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.doc_checks.thesis_source_tracking import (
    KIND_MALFORMED,
    KIND_MISSING,
    KIND_NO_HASH,
    KIND_UPDATED,
    check_thesis_source_tracking,
    main,
    parse_section_sources,
    stamp_section_sources,
)

_SECTION = "thesis/chapters/01_introduction/01_background.md"


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)
    return result.stdout.decode("utf-8").strip()


def _init_repo(repo_dir: Path) -> None:
    _git(["init", "-q"], repo_dir)
    _git(["config", "user.email", "test@example.com"], repo_dir)
    _git(["config", "user.name", "Test"], repo_dir)
    _git(["config", "commit.gpgsign", "false"], repo_dir)
    _git(["config", "core.autocrlf", "false"], repo_dir)


def _write(repo_dir: Path, relative_path: str, content: str) -> None:
    path = repo_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


def _commit_all(repo_dir: Path) -> None:
    _git(["add", "-A"], repo_dir)
    _git(["commit", "-q", "-m", "test commit"], repo_dir)


def _blob_hash(repo_dir: Path, relative_path: str) -> str:
    return _git(["rev-parse", f"HEAD:{relative_path}"], repo_dir)


def _section(sources: list[str], state: str = "執筆中") -> str:
    entries = "".join(f"  - {source}\n" for source in sources)
    return (
        "<!--\n"
        "見出し: 1.1　研究背景\n"
        f"状態: {state}\n"
        "依拠する正本:\n"
        f"{entries}"
        "-->\n"
        "\n"
        "## 1.1　研究背景\n"
        "\n"
        "本文．\n"
    )


def _setup_repo_with_source(repo_dir: Path) -> str:
    """正本 docs/a.md をコミットし、その blob ハッシュを返す。"""
    _init_repo(repo_dir)
    _write(repo_dir, "docs/a.md", "# A\n\n初版\n")
    _commit_all(repo_dir)
    return _blob_hash(repo_dir, "docs/a.md")


# --- 解析 ---


def test_parse_reads_path_and_hash() -> None:
    """`- パス @ ハッシュ` の行からパスとハッシュを読む。"""
    parsed = parse_section_sources(_section(["docs/a.md @ 0123456789"]), _SECTION)

    assert len(parsed.references) == 1
    ref = parsed.references[0]
    assert ref.path == "docs/a.md"
    assert ref.recorded_hash == "0123456789"
    assert ref.line == 5
    assert parsed.malformed == []


def test_parse_ignores_placeholder() -> None:
    """未着手の節のプレースホルダ `（執筆時に記入）` は検査対象にしない。"""
    parsed = parse_section_sources(_section(["（執筆時に記入）"]), _SECTION)

    assert parsed.references == []
    assert parsed.malformed == []


def test_parse_entry_without_hash() -> None:
    """ハッシュの無い行はパスのみを読み、ハッシュは None とする。"""
    parsed = parse_section_sources(_section(["docs/a.md"]), _SECTION)

    assert parsed.references[0].recorded_hash is None


def test_parse_reports_malformed_entry() -> None:
    """書式に合わない行（ハッシュが16進数でない等）は書式不正とする。"""
    parsed = parse_section_sources(_section(["docs/a.md @ 未記入"]), _SECTION)

    assert parsed.references == []
    assert len(parsed.malformed) == 1
    assert parsed.malformed[0].kind == KIND_MALFORMED
    assert parsed.malformed[0].line == 5


def test_parse_stops_at_next_key() -> None:
    """「依拠する正本」の後に別の項目が来たら、それ以降は正本として読まない。"""
    text = (
        "<!--\n"
        "依拠する正本:\n"
        "  - docs/a.md @ 0123456789\n"
        "目安: 10 ページ\n"
        "  - docs/b.md @ 0123456789\n"
        "-->\n"
    )

    parsed = parse_section_sources(text, _SECTION)

    assert [ref.path for ref in parsed.references] == ["docs/a.md"]


def test_parse_ignores_body_outside_metadata_comment() -> None:
    """冒頭の HTML コメントの外（本文）は解析しない。"""
    text = "## 1.1　研究背景\n\n依拠する正本:\n  - docs/a.md @ 0123456789\n"

    parsed = parse_section_sources(text, _SECTION)

    assert parsed.references == []


def test_parse_handles_crlf() -> None:
    """改行コードが CRLF でも同じ結果になる。"""
    text = _section(["docs/a.md @ 0123456789"]).replace("\n", "\r\n")

    parsed = parse_section_sources(text, _SECTION)

    assert parsed.references[0].recorded_hash == "0123456789"


# --- 検出 ---


def test_no_finding_when_source_unchanged(tmp_path: Path) -> None:
    """正本が記録時点から変わっていなければ何も検出しない。"""
    blob = _setup_repo_with_source(tmp_path)
    _write(tmp_path, _SECTION, _section([f"docs/a.md @ {blob[:10]}"]))
    _commit_all(tmp_path)

    assert check_thesis_source_tracking(project_root=tmp_path) == []


def test_detects_updated_source(tmp_path: Path) -> None:
    """正本を更新すると、それに依拠する節が要見直しとして検出される。"""
    old_blob = _setup_repo_with_source(tmp_path)
    _write(tmp_path, _SECTION, _section([f"docs/a.md @ {old_blob[:10]}"]))
    _commit_all(tmp_path)
    _write(tmp_path, "docs/a.md", "# A\n\n改訂版\n")
    _commit_all(tmp_path)
    new_blob = _blob_hash(tmp_path, "docs/a.md")

    findings = check_thesis_source_tracking(project_root=tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind == KIND_UPDATED
    assert finding.section_file == _SECTION
    assert finding.source_path == "docs/a.md"
    assert finding.recorded_hash == old_blob[:10]
    assert finding.current_hash == new_blob[:10]
    assert finding.diff_command == f"git diff {old_blob[:10]} {new_blob[:10]}"


def test_uncommitted_source_change_is_not_detected(tmp_path: Path) -> None:
    """未コミットの正本の変更は検出しない（HEAD 時点の版と比較するため）。"""
    blob = _setup_repo_with_source(tmp_path)
    _write(tmp_path, _SECTION, _section([f"docs/a.md @ {blob[:10]}"]))
    _commit_all(tmp_path)
    _write(tmp_path, "docs/a.md", "# A\n\n未コミットの変更\n")

    assert check_thesis_source_tracking(project_root=tmp_path) == []


def test_detects_missing_source(tmp_path: Path) -> None:
    """正本が移動・削除されて見つからない場合は検出する。"""
    _setup_repo_with_source(tmp_path)
    _write(tmp_path, _SECTION, _section(["docs/moved.md @ 0123456789"]))
    _commit_all(tmp_path)

    findings = check_thesis_source_tracking(project_root=tmp_path)

    assert [finding.kind for finding in findings] == [KIND_MISSING]


def test_detects_missing_hash(tmp_path: Path) -> None:
    """パスのみでハッシュが記録されていない正本は未記録として検出する。"""
    _setup_repo_with_source(tmp_path)
    _write(tmp_path, _SECTION, _section(["docs/a.md"]))
    _commit_all(tmp_path)

    findings = check_thesis_source_tracking(project_root=tmp_path)

    assert [finding.kind for finding in findings] == [KIND_NO_HASH]


def test_directory_source_detects_change_of_child(tmp_path: Path) -> None:
    """ディレクトリを正本にした場合、配下のファイルの更新で要見直しになる。"""
    _setup_repo_with_source(tmp_path)
    tree = _git(["rev-parse", "HEAD:docs"], tmp_path)
    _write(tmp_path, _SECTION, _section([f"docs/ @ {tree[:10]}"]))
    _commit_all(tmp_path)
    assert check_thesis_source_tracking(project_root=tmp_path) == []

    _write(tmp_path, "docs/b.md", "# B\n")
    _commit_all(tmp_path)

    findings = check_thesis_source_tracking(project_root=tmp_path)

    assert [(finding.kind, finding.source_path) for finding in findings] == [
        (KIND_UPDATED, "docs/")
    ]


def test_japanese_path_source(tmp_path: Path) -> None:
    """日本語を含むパスの正本も比較できる。"""
    _init_repo(tmp_path)
    _write(tmp_path, "docs/結果.md", "# 結果\n")
    _commit_all(tmp_path)
    blob = _blob_hash(tmp_path, "docs/結果.md")
    _write(tmp_path, _SECTION, _section([f"docs/結果.md @ {blob[:10]}"]))
    _commit_all(tmp_path)

    assert check_thesis_source_tracking(project_root=tmp_path) == []


def test_unstarted_section_is_skipped(tmp_path: Path) -> None:
    """状態が「未着手」の節は、ハッシュ未記録や正本の更新があっても検査しない。"""
    _setup_repo_with_source(tmp_path)
    _write(tmp_path, _SECTION, _section(["docs/a.md", "docs/moved.md @ 0123456789"], "未着手"))
    _commit_all(tmp_path)

    assert check_thesis_source_tracking(project_root=tmp_path) == []


def test_parse_reads_state() -> None:
    """メタ情報欄の「状態:」を読む。"""
    parsed = parse_section_sources(_section(["docs/a.md"], "初稿"), _SECTION)

    assert parsed.state == "初稿"
    assert [ref.path for ref in parsed.references] == ["docs/a.md"]


def test_git_failure_raises_runtime_error(tmp_path: Path) -> None:
    """git リポジトリでない場所では「正本が見つからない」ではなく例外にする。"""
    _write(tmp_path, _SECTION, _section(["docs/a.md @ 0123456789"]))

    with pytest.raises(RuntimeError, match="正本のハッシュを取得できませんでした"):
        check_thesis_source_tracking(project_root=tmp_path)


def test_no_thesis_directory(tmp_path: Path) -> None:
    """`thesis/chapters/` が無ければ何も検出しない。"""
    _setup_repo_with_source(tmp_path)

    assert check_thesis_source_tracking(project_root=tmp_path) == []


# --- 記録（--stamp） ---


def test_stamp_records_current_hash(tmp_path: Path) -> None:
    """stamp でハッシュ未記録・古いハッシュを現在の値に書き換え、検出が解消する。"""
    old_blob = _setup_repo_with_source(tmp_path)
    _write(tmp_path, "docs/b.md", "# B\n")
    _write(tmp_path, _SECTION, _section([f"docs/a.md @ {old_blob[:10]}", "docs/b.md"]))
    _commit_all(tmp_path)
    _write(tmp_path, "docs/a.md", "# A\n\n改訂版\n")
    _commit_all(tmp_path)
    assert len(check_thesis_source_tracking(project_root=tmp_path)) == 2

    not_found = stamp_section_sources(Path(_SECTION), project_root=tmp_path)

    assert not_found == []
    text = (tmp_path / _SECTION).read_text(encoding="utf-8")
    assert f"  - docs/a.md @ {_blob_hash(tmp_path, 'docs/a.md')[:10]}\n" in text
    assert f"  - docs/b.md @ {_blob_hash(tmp_path, 'docs/b.md')[:10]}\n" in text
    assert check_thesis_source_tracking(project_root=tmp_path) == []


def test_stamp_preserves_other_lines_and_crlf(tmp_path: Path) -> None:
    """stamp は該当行以外を変えず、CRLF の改行コードも保持する。"""
    blob = _setup_repo_with_source(tmp_path)
    original = _section(["docs/a.md", "（執筆時に記入）"]).replace("\n", "\r\n")
    _write(tmp_path, _SECTION, original)

    stamp_section_sources(Path(_SECTION), project_root=tmp_path)

    expected = original.replace("  - docs/a.md\r\n", f"  - docs/a.md @ {blob[:10]}\r\n")
    assert (tmp_path / _SECTION).read_bytes().decode("utf-8") == expected


def test_stamp_reports_missing_source(tmp_path: Path) -> None:
    """HEAD に無い正本の行は書き換えず、そのパスを返す。"""
    _setup_repo_with_source(tmp_path)
    original = _section(["docs/moved.md @ 0123456789"])
    _write(tmp_path, _SECTION, original)

    not_found = stamp_section_sources(Path(_SECTION), project_root=tmp_path)

    assert not_found == ["docs/moved.md"]
    assert (tmp_path / _SECTION).read_text(encoding="utf-8") == original


# --- コマンドライン ---


def test_main_reports_findings_with_exit_zero(tmp_path: Path, capsys) -> None:
    """検出結果を表示し、要見直しがあっても終了コードは0とする。"""
    _setup_repo_with_source(tmp_path)
    _write(tmp_path, _SECTION, _section(["docs/a.md @ 0123456789"]))
    _commit_all(tmp_path)

    exit_code = main([], project_root=tmp_path)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"{_SECTION}:5 [{KIND_UPDATED}] docs/a.md" in output
    assert "git diff 0123456789" in output


def test_main_stamp_returns_one_when_source_missing(tmp_path: Path) -> None:
    """--stamp で正本が見つからない行があれば終了コード1を返す。"""
    _setup_repo_with_source(tmp_path)
    _write(tmp_path, _SECTION, _section(["docs/moved.md"]))

    assert main(["--stamp", _SECTION], project_root=tmp_path) == 1
