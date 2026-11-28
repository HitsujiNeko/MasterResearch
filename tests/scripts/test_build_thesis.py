"""scripts/build_thesis.py（修士論文の md → docx ビルド）のテスト。

対象は ``src`` パッケージ外のスクリプトのため、ファイルパスを指定して読み込む。
結合順・コマンド組み立て・実行ファイル探索・エラー処理は pandoc なしで検証し、
実際の docx 生成（図表番号・目次・メタ情報欄の非出力）は pandoc と pandoc-crossref が
ある環境でのみ検証する（CI には pandoc を入れていないため skip される）。
Word（COM）による目次更新・PDF 化はテストしない（手動の目視確認で扱う）。
"""

from __future__ import annotations

import json
import os
import re
import stat
import struct
import subprocess
import zipfile
import zlib
from pathlib import Path

import pytest

from tests.helpers import load_script_module

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_thesis.py"


target = load_script_module(SCRIPT_PATH, "build_thesis")


def _find_tools() -> tuple[str, str] | None:
    """pandoc と pandoc-crossref の両方が見つかればそのパスを返す。"""
    try:
        return target.find_executable("pandoc"), target.find_executable("pandoc-crossref")
    except FileNotFoundError:
        return None


TOOLS = _find_tools()
requires_pandoc = pytest.mark.skipif(TOOLS is None, reason="pandoc と pandoc-crossref が必要")


def _touch(path: Path, text: str = "") -> Path:
    """親ディレクトリを作ってファイルを書く。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_png(path: Path, width: int = 4, height: int = 3) -> None:
    """外部ライブラリを使わずに単色の PNG を書く（図の埋め込み確認用）。"""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png + chunk(b"IEND", b""))


def _document_xml(docx: Path) -> str:
    """docx の本文 XML を読む。"""
    with zipfile.ZipFile(docx) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def _paragraph_texts(document_xml: str) -> list[str]:
    """本文 XML から段落ごとのテキストを取り出す。"""
    paragraphs = re.findall(r"<w:p[ >].*?</w:p>", document_xml, re.S)
    return ["".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)) for p in paragraphs]


class TestCollectChapterFiles:
    """章・節ファイルの収集と結合順のテスト。"""

    def test_orders_by_relative_path_parts(self, tmp_path: Path) -> None:
        files = [
            _touch(tmp_path / "02_data" / "00_chapter.md"),
            _touch(tmp_path / "01_intro" / "05_structure.md"),
            _touch(tmp_path / "01_intro" / "00_chapter.md"),
            _touch(tmp_path / "90_back" / "01_ack.md"),
        ]
        result = target.collect_chapter_files(tmp_path)
        assert result == [files[2], files[1], files[0], files[3]]

    def test_ignores_non_markdown(self, tmp_path: Path) -> None:
        md = _touch(tmp_path / "01_intro" / "00_chapter.md")
        _touch(tmp_path / "01_intro" / "memo.txt")
        _touch(tmp_path / "01_intro" / ".gitkeep")
        assert target.collect_chapter_files(tmp_path) == [md]

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="ディレクトリ"):
            target.collect_chapter_files(tmp_path / "none")

    def test_empty_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="md ファイル"):
            target.collect_chapter_files(tmp_path)

    def test_repository_skeleton_starts_with_chapter_1(self) -> None:
        """追跡している骨組みが第1章の章見出しファイルから始まる。"""
        files = target.collect_chapter_files(target.CHAPTERS_DIR)
        assert files[0].relative_to(target.CHAPTERS_DIR).as_posix() == (
            "01_introduction/00_chapter.md"
        )


class TestFindExecutable:
    """実行ファイル探索のテスト。"""

    def test_explicit_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="tool"):
            target.find_executable("tool", str(tmp_path / "no_tool"))

    def test_falls_back_to_conda_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PATH に無くても、実行中の conda 環境の Library/bin から見つける。"""
        bin_dir = tmp_path / "env" / "Library" / "bin"
        # Windows は拡張子つき、POSIX は実行権限つきの名前で探すため両方置く
        for name in ("thesis_tool_x", "thesis_tool_x.exe"):
            path = _touch(bin_dir / name)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        monkeypatch.setattr(target.sys, "prefix", str(tmp_path / "env"))
        found = target.find_executable("thesis_tool_x")
        assert Path(found).parent == bin_dir

    def test_not_found_message_mentions_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(target.sys, "prefix", str(tmp_path))
        with pytest.raises(FileNotFoundError, match="environment.yml"):
            target.find_executable("thesis_tool_missing")


def test_build_pandoc_command_wires_all_inputs(tmp_path: Path) -> None:
    inputs = [tmp_path / "a.md", tmp_path / "b.md"]
    command = target.build_pandoc_command(
        "pandoc",
        "crossref",
        inputs,
        tmp_path / "out.docx",
        tmp_path / "meta.yaml",
        tmp_path / "ref.docx",
        [tmp_path / "r1", tmp_path / "r2"],
        [tmp_path / "gen.bib", tmp_path / "extra.bib"],
        tmp_path / "style.csl",
    )
    assert command[0] == "pandoc"
    assert command[1:3] == [str(path) for path in inputs]
    assert "--filter=crossref" in command
    assert f"--metadata-file={tmp_path / 'meta.yaml'}" in command
    assert f"--reference-doc={tmp_path / 'ref.docx'}" in command
    assert "--toc" in command
    assert f"--toc-depth={target.TOC_DEPTH}" in command
    assert f"--resource-path={tmp_path / 'r1'}{os.pathsep}{tmp_path / 'r2'}" in command
    assert f"--bibliography={tmp_path / 'gen.bib'}" in command
    assert f"--bibliography={tmp_path / 'extra.bib'}" in command
    assert f"--csl={tmp_path / 'style.csl'}" in command
    assert command[-1] == f"--output={tmp_path / 'out.docx'}"


def test_build_pandoc_command_runs_crossref_before_citeproc(tmp_path: Path) -> None:
    """pandoc-crossref を citeproc より先に適用する（@fig: を引用と誤認させないため）。"""
    command = target.build_pandoc_command(
        "pandoc",
        "crossref",
        [tmp_path / "a.md"],
        tmp_path / "out.docx",
        tmp_path / "meta.yaml",
        tmp_path / "ref.docx",
        [tmp_path],
        [tmp_path / "gen.bib"],
        tmp_path / "style.csl",
    )
    assert command.index("--filter=crossref") < command.index("--citeproc")


def test_build_pandoc_command_runs_lua_filters_after_crossref_and_citeproc(
    tmp_path: Path,
) -> None:
    """Lua フィルタは crossref と citeproc の後に指定順で適用する（表題・参考文献も対象）。"""
    first, second = tmp_path / "a.lua", tmp_path / "b.lua"
    command = target.build_pandoc_command(
        "pandoc",
        "crossref",
        [tmp_path / "a.md"],
        tmp_path / "out.docx",
        tmp_path / "meta.yaml",
        tmp_path / "ref.docx",
        [tmp_path],
        [tmp_path / "gen.bib"],
        tmp_path / "style.csl",
        (first, second),
    )
    crossref = command.index("--filter=crossref")
    lua_first = command.index(f"--lua-filter={first}")
    lua_second = command.index(f"--lua-filter={second}")
    assert crossref < command.index("--citeproc") < lua_first < lua_second


def test_build_pandoc_command_without_lua_filters(tmp_path: Path) -> None:
    """Lua フィルタを指定しなければ --lua-filter を付けない。"""
    command = target.build_pandoc_command(
        "pandoc",
        "crossref",
        [tmp_path / "a.md"],
        tmp_path / "out.docx",
        tmp_path / "meta.yaml",
        tmp_path / "ref.docx",
        [tmp_path],
        [tmp_path / "gen.bib"],
        tmp_path / "style.csl",
    )
    assert not [arg for arg in command if arg.startswith("--lua-filter")]


def test_latin_symbols_filter_exists() -> None:
    """既定の欧文の記号の Lua フィルタがリポジトリにある（build_docx が既定で渡す）。"""
    assert target.LATIN_SYMBOLS_FILTER.is_file()


def _latin_symbol_spans(node: object, context: str = "body") -> list[tuple[str, str, str]]:
    """pandoc の JSON の AST から、custom-style 付きの Span を（文脈・スタイル名・文字列）で集める。

    文脈は、Span を含む表（Table）・脚注（Note）を「/」でつないで表す（例: ``body/Table/Note``）。
    """
    spans: list[tuple[str, str, str]] = []
    if isinstance(node, list):
        for child in node:
            spans.extend(_latin_symbol_spans(child, context))
    elif isinstance(node, dict):
        kind = node.get("t")
        if kind == "Span":
            attributes = dict(node["c"][0][2])
            if "custom-style" in attributes:
                text = "".join(item.get("c", "") for item in node["c"][1] if item["t"] == "Str")
                spans.append((context, attributes["custom-style"], text))
        if kind in ("Table", "Note"):
            context = f"{context}/{kind}"
        for child in node.values():
            spans.extend(_latin_symbol_spans(child, context))
    return spans


@pytest.mark.skipif(TOOLS is None, reason="pandoc が必要")
class TestLatinSymbolsFilter:
    """欧文の記号を文字スタイル付きの Span に分ける Lua フィルタ単体のテスト（pandoc の AST）。"""

    @staticmethod
    def _run(markdown: str) -> dict:
        """md に Lua フィルタを適用した pandoc の JSON の AST を返す。"""
        pandoc, _ = TOOLS
        result = subprocess.run(
            [pandoc, "--from=markdown", "--to=json", f"--lua-filter={target.LATIN_SYMBOLS_FILTER}"],
            input=markdown,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(result.stdout)

    def test_splits_consecutive_trailing_and_lone_signs(self) -> None:
        """「°」の連続・Str の末尾・「°」だけの Str をそれぞれ 1 文字ずつ分け、他の文字は残す。"""
        document = self._run("連続 °°C と末尾の と°\n\n°\n")
        spans = _latin_symbol_spans(document["blocks"])
        assert spans == [("body", "Latin Symbol", "°")] * 4
        strings = [item["c"] for item in document["blocks"][0]["c"] if item["t"] == "Str"]
        assert strings == ["連続", "C", "と末尾の", "と"]

    def test_splits_minus_plus_minus_and_multiplication_signs(self) -> None:
        """「−」「±」「×」も分け、本文は Latin Symbol・表は Latin Symbol Sans にする。"""
        document = self._run(
            "相関は −0.991，平均 ± 6 倍，3 × 3 画素．\n\n| LST − 気温（°C） |\n|---|\n| −20 °C |\n"
        )
        assert _latin_symbol_spans(document["blocks"]) == [
            ("body", "Latin Symbol", "−"),
            ("body", "Latin Symbol", "±"),
            ("body", "Latin Symbol", "×"),
            ("body/Table", "Latin Symbol Sans", "−"),
            ("body/Table", "Latin Symbol Sans", "°"),
            ("body/Table", "Latin Symbol Sans", "−"),
            ("body/Table", "Latin Symbol Sans", "°"),
        ]

    def test_similar_characters_are_not_split(self) -> None:
        """対象外の似た文字（ハイフン・全角マイナス・ダッシュ・波ダッシュ・上付き 2）は分けない。"""
        document = self._run("a-b，－1，Köppen–Geiger，—，1〜2，km²．\n")
        assert _latin_symbol_spans(document["blocks"]) == []

    def test_title_in_metadata_uses_serif_style(self) -> None:
        """表紙の題目（メタデータ）の「°」も分ける（表紙は明朝の文脈）。"""
        document = self._run("---\ntitle: 題目 30 °C\n---\n\n本文\n")
        assert _latin_symbol_spans(document["meta"]) == [("body", "Latin Symbol", "°")]

    def test_footnote_in_table_uses_serif_style(self) -> None:
        """表の中の脚注の本文は、明朝の脚注スタイルで描かれるため Latin Symbol にする。"""
        document = self._run(
            "| 項目[^1] | 気温（°C） |\n|---|---|\n| a | −20 °C |\n\n[^1]: 表の脚注 °C\n"
        )
        assert sorted(_latin_symbol_spans(document["blocks"])) == [
            ("body/Table", "Latin Symbol Sans", "°"),
            ("body/Table", "Latin Symbol Sans", "°"),
            ("body/Table", "Latin Symbol Sans", "−"),
            ("body/Table/Note", "Latin Symbol", "°"),
        ]

    @pytest.mark.parametrize(
        "markdown",
        [
            "# 見出し °C[^1]\n\n[^1]: 見出しの脚注 °C\n",
            "![図題 °C[^1]](a.png)\n\n[^1]: 図題の脚注 °C\n",
        ],
        ids=["heading", "figure"],
    )
    def test_footnote_in_heading_or_figure_uses_serif_style(self, markdown: str) -> None:
        """見出し・図題の中の脚注の本文も明朝の文脈（Latin Symbol）、外側は Latin Symbol Sans。"""
        spans = _latin_symbol_spans(self._run(markdown)["blocks"])
        assert ("body/Note", "Latin Symbol", "°") in spans
        assert ("body", "Latin Symbol Sans", "°") in spans
        assert {style for _, style, _ in spans} == {"Latin Symbol", "Latin Symbol Sans"}

    def test_document_with_degree_sign_only_in_code_is_unchanged(self) -> None:
        """「°」がコードの中にしか無い文書は、フィルタの有無で AST が変わらない。"""
        markdown = "# 見出し\n\n本文 30 度．`°C` はコード．\n"
        pandoc, _ = TOOLS
        plain = subprocess.run(
            [pandoc, "--from=markdown", "--to=json"],
            input=markdown,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert self._run(markdown) == json.loads(plain.stdout)


@pytest.mark.parametrize(
    "missing", ["metadata_file", "csl_file", "extra_bibliography", "latin_symbols_filter"]
)
def test_build_docx_requires_input_files(tmp_path: Path, missing: str) -> None:
    """metadata・CSL・手書きの .bib・Lua フィルタのいずれかが無ければ pandoc を呼ぶ前に失敗する。"""
    _touch(tmp_path / "chapters" / "01" / "00.md", "# 第1章")
    with pytest.raises(FileNotFoundError, match="ファイルがありません"):
        target.build_docx(
            tmp_path / "chapters",
            tmp_path / "out.docx",
            pandoc="pandoc",
            crossref="crossref",
            **{missing: tmp_path / "none"},
        )


class TestExtraBibliography:
    """手書きの .bib の引用キーの検査のテスト。"""

    def test_keys_skip_comments_and_non_entries(self) -> None:
        """@comment・@string と、% でコメントアウトした行のエントリは引用キーに数えない。"""
        text = (
            "% @book{commented_out,\n"
            "@string{ja = {Japanese}}\n"
            "@comment{note, x}\n"
            "@book{masuda2011,\n  title = {本},\n}\n"
            "  @Online{ usgs_landsat , url = {x}}\n"
        )
        assert target.bibliography_keys(text) == ["masuda2011", "usgs_landsat"]

    def test_keys_handle_bom_and_parenthesized_entries(self) -> None:
        """先頭の BOM の直後のエントリと「@book(key, …)」形式のエントリも拾う。"""
        text = "\ufeff@book{first,\n}\n@book(second,\n  title = {x})\n"
        assert target.bibliography_keys(text) == ["first", "second"]

    def test_accepts_repository_extra_bibliography(self) -> None:
        """リポジトリの手書きの .bib は S 番号のキー・重複キーを含まない。"""
        target.check_extra_bibliography(target.EXTRA_BIBLIOGRAPHY.read_text(encoding="utf-8"))

    def test_rejects_reserved_and_duplicate_keys(self) -> None:
        """S 番号の形のキーと、手書き分の中での重複キーを報告する。"""
        extra = "@book{S99,\n}\n@book{dup,\n}\n@book{dup,\n}\n"
        with pytest.raises(target.make_thesis_bib.BibliographyError) as info:
            target.check_extra_bibliography(extra)
        problems = info.value.problems
        assert any(problem.startswith("S99:") for problem in problems)
        assert "dup: 手書きの .bib で引用キーが重複しています" in problems

    def test_build_docx_rejects_reserved_key_before_pandoc(self, tmp_path: Path) -> None:
        """手書きの .bib に S 番号の形のキーがあれば、.bib の生成・pandoc の実行前に失敗する。"""
        _touch(tmp_path / "chapters" / "01" / "00.md", "# 第1章")
        extra = _touch(tmp_path / "extra.bib", "@book{S99,\n  title = {x},\n}\n")
        output = tmp_path / "build" / "out.docx"
        with pytest.raises(target.make_thesis_bib.BibliographyError, match="S99"):
            target.build_docx(
                tmp_path / "chapters",
                output,
                pandoc="pandoc_not_called",
                crossref="crossref_not_called",
                extra_bibliography=extra,
            )
        assert not (output.parent / target.GENERATED_BIBLIOGRAPHY_NAME).exists()


def test_export_pdf_rejects_non_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows"):
        target.export_pdf_with_word(tmp_path / "a.docx", tmp_path / "a.pdf")


class TestMain:
    """main の終了コードとエラー表示のテスト。"""

    def test_returns_2_when_tool_missing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def missing(name: str, explicit: str | None = None) -> str:
            raise FileNotFoundError(f"{name} が見つかりません")

        monkeypatch.setattr(target, "find_executable", missing)
        assert target.main([]) == target.EXIT_ERROR
        assert "pandoc が見つかりません" in capsys.readouterr().err

    def test_returns_2_and_shows_pandoc_stderr(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def failing_build(*args: object, **kwargs: object) -> str:
            raise subprocess.CalledProcessError(64, ["pandoc"], stderr="YAML parse exception")

        monkeypatch.setattr(target, "find_executable", lambda name, explicit=None: name)
        monkeypatch.setattr(target, "build_docx", failing_build)
        assert target.main(["--output", str(tmp_path / "x.docx")]) == target.EXIT_ERROR
        err = capsys.readouterr().err
        assert "終了コード 64" in err
        assert "YAML parse exception" in err

    def test_strict_fails_on_warnings(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--strict では図の欠落・未定義の参照等の警告を失敗にする（無指定では成功）。"""
        warning = "[WARNING] Could not fetch resource figures/none.png"
        monkeypatch.setattr(target, "find_executable", lambda name, explicit=None: name)
        monkeypatch.setattr(target, "build_docx", lambda *args, **kwargs: warning)
        output = str(tmp_path / "x.docx")
        assert target.main(["--output", output]) == target.EXIT_OK
        assert target.main(["--output", output, "--strict"]) == target.EXIT_ERROR
        assert "--strict" in capsys.readouterr().err

    def test_returns_2_and_lists_bibliography_problems(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """文献 DB と引用用書誌の不整合は、問題の一覧を表示して終了コード 2 を返す。"""

        def inconsistent_build(*args: object, **kwargs: object) -> str:
            raise target.make_thesis_bib.BibliographyError(["S19: 引用用書誌に行がありません"])

        monkeypatch.setattr(target, "find_executable", lambda name, explicit=None: name)
        monkeypatch.setattr(target, "build_docx", inconsistent_build)
        assert target.main(["--output", str(tmp_path / "x.docx")]) == target.EXIT_ERROR
        err = capsys.readouterr().err
        assert ".bib を用意できません" in err
        assert "S19: 引用用書誌に行がありません" in err

    def test_returns_2_when_pandoc_times_out(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """pandoc の打ち切りでは Word 用の案内を出さない。"""

        def hanging_pandoc(*args: object, **kwargs: object) -> str:
            raise subprocess.TimeoutExpired(["pandoc"], target.PANDOC_TIMEOUT_SECONDS)

        monkeypatch.setattr(target, "find_executable", lambda name, explicit=None: name)
        monkeypatch.setattr(target, "build_docx", hanging_pandoc)
        assert target.main(["--output", str(tmp_path / "x.docx")]) == target.EXIT_ERROR
        err = capsys.readouterr().err
        assert "pandoc が" in err
        assert "WINWORD.EXE" not in err

    def test_returns_2_when_word_times_out(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def hanging_word(docx: Path, pdf: Path) -> None:
            raise subprocess.TimeoutExpired(["powershell"], target.WORD_TIMEOUT_SECONDS)

        monkeypatch.setattr(target, "find_executable", lambda name, explicit=None: name)
        monkeypatch.setattr(target, "build_docx", lambda *args, **kwargs: "")
        monkeypatch.setattr(target, "export_pdf_with_word", hanging_word)
        assert target.main(["--output", str(tmp_path / "x.docx"), "--pdf"]) == target.EXIT_ERROR
        assert "打ち切りました" in capsys.readouterr().err


class TestAddSpaceAfterTables:
    """表の直後の本文段落に空きを入れる後処理のテスト（pandoc 不要）。"""

    @staticmethod
    def _xml(next_paragraph_ppr: str) -> str:
        return (
            "<w:body><w:tbl><w:tr /></w:tbl>"
            f"<w:p><w:pPr>{next_paragraph_ppr}</w:pPr><w:r><w:t>本文</w:t></w:r></w:p></w:body>"
        )

    @pytest.mark.parametrize("style", ["BodyText", "FirstParagraph"])
    def test_inserts_spacing_after_pstyle_of_body_paragraph(self, style: str) -> None:
        """表に続く本文の段落には、段落スタイルの直後に段落前の空きを入れる。"""
        updated = target.add_space_after_tables(self._xml(f'<w:pStyle w:val="{style}" />'))
        assert f'<w:pStyle w:val="{style}" /><w:spacing w:beforeLines="100" />' in updated

    @pytest.mark.parametrize("style", ["TableCaption", "Heading2", "Compact"])
    def test_leaves_non_body_paragraphs(self, style: str) -> None:
        """見出し・表題など本文以外の段落（スタイルで空きを持つもの）は変えない。"""
        xml = self._xml(f'<w:pStyle w:val="{style}" />')
        assert target.add_space_after_tables(xml) == xml

    @pytest.mark.parametrize(
        "rest", ['<w:spacing w:before="120" />', "<w:keepNext />", "<w:pageBreakBefore />"]
    )
    def test_leaves_paragraph_with_preceding_properties(self, rest: str) -> None:
        """すでに空きの指定がある段落や、spacing より前に置く要素を持つ段落は変えない。"""
        xml = self._xml(f'<w:pStyle w:val="BodyText" />{rest}')
        assert target.add_space_after_tables(xml) == xml

    def test_skips_bookmarks_between_table_and_paragraph(self) -> None:
        """表と段落の間に表の番号の目印（bookmark）があっても空きを入れる。"""
        xml = (
            '<w:tbl><w:tr /></w:tbl>\n<w:bookmarkEnd w:id="9" />\n'
            '<w:p><w:pPr><w:pStyle w:val="BodyText" /></w:pPr></w:p>'
        )
        assert 'w:beforeLines="100"' in target.add_space_after_tables(xml)

    def test_only_paragraphs_right_after_tables(self) -> None:
        """表の直後ではない本文の段落は変えない。"""
        xml = '<w:p><w:pPr><w:pStyle w:val="BodyText" /></w:pPr></w:p>' + self._xml(
            '<w:pStyle w:val="BodyText" />'
        )
        updated = target.add_space_after_tables(xml)
        assert updated.count("w:beforeLines") == 1
        assert updated.startswith('<w:p><w:pPr><w:pStyle w:val="BodyText" /></w:pPr></w:p>')

    def test_uses_given_space_and_rejects_negative(self) -> None:
        """空きの量は引数で変えられ、負の値は止める。"""
        xml = self._xml('<w:pStyle w:val="BodyText" />')
        assert 'w:beforeLines="50"' in target.add_space_after_tables(xml, before_lines=50)
        with pytest.raises(ValueError):
            target.add_space_after_tables(xml, before_lines=-1)

    def test_docx_roundtrip_keeps_other_parts(self, tmp_path: Path) -> None:
        """docx を書き戻しても、document.xml 以外のパーツと並びは変わらない。"""
        docx = tmp_path / "a.docx"
        with zipfile.ZipFile(docx, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types />")
            archive.writestr("word/document.xml", self._xml('<w:pStyle w:val="BodyText" />'))
            archive.writestr("word/styles.xml", "<w:styles />")
        assert target.add_space_after_tables_in_docx(docx) == 1
        with zipfile.ZipFile(docx) as archive:
            assert archive.namelist() == [
                "[Content_Types].xml",
                "word/document.xml",
                "word/styles.xml",
            ]
            assert archive.read("word/styles.xml") == b"<w:styles />"
            assert b'w:beforeLines="100"' in archive.read("word/document.xml")

    def test_docx_missing_raises(self, tmp_path: Path) -> None:
        """docx が無いときは止める。"""
        with pytest.raises(FileNotFoundError):
            target.add_space_after_tables_in_docx(tmp_path / "missing.docx")


@requires_pandoc
class TestBuildWithPandoc:
    """pandoc と pandoc-crossref による実際の docx 生成のテスト。"""

    def test_builds_repository_skeleton(self, tmp_path: Path) -> None:
        """追跡している骨組みから docx が生成され、メタ情報欄は出力されない。"""
        pandoc, crossref = TOOLS
        output = tmp_path / "thesis.docx"
        target.build_docx(target.CHAPTERS_DIR, output, pandoc=pandoc, crossref=crossref)
        document = _document_xml(output)
        texts = _paragraph_texts(document)
        assert "第1章　はじめに" in texts
        assert "1.4　研究課題" in texts
        assert "依拠する正本" not in document
        # 目次は Word のフィールドとして出力される
        assert re.search(r"TOC \\o", document)
        # 用紙・余白は reference.docx から引き継がれる
        # （pandoc は属性の順序を並べ替えるため、属性ごとに確認する）
        margins = re.search(r"<w:pgMar [^>]*>", document).group(0)
        for attr in ('w:top="1985"', 'w:right="1701"', 'w:bottom="1701"', 'w:left="1701"'):
            assert attr in margins

    def test_numbers_figures_and_tables(self, tmp_path: Path) -> None:
        """図-1 は図の下・表-1 は表の上に番号つきで出力され、本文参照も「図-1」になる。"""
        pandoc, crossref = TOOLS
        chapters = tmp_path / "chapters"
        _write_png(tmp_path / "figures" / "a.png")
        _touch(
            chapters / "01_intro" / "00_chapter.md",
            "# 第1章　はじめに\n\n"
            "@fig:a と @tbl:a を参照する．\n\n"
            "![図の題目](figures/a.png){#fig:a}\n\n"
            "| 変数 | 単位 |\n|---|---|\n| LST | °C |\n\n"
            ": 表の題目 {#tbl:a}\n\n"
            "表の後の本文．\n",
        )
        output = tmp_path / "out.docx"
        warnings = target.build_docx(
            chapters,
            output,
            pandoc=pandoc,
            crossref=crossref,
            resource_paths=(tmp_path,),
        )
        assert "Could not fetch resource" not in warnings
        document = _document_xml(output)
        texts = _paragraph_texts(document)
        assert "図-1　図の題目" in texts
        assert "表-1　表の題目" in texts
        assert "図-1 と 表-1 を参照する．" in texts
        # 図題は図（drawing）の後、表題は表（w:tbl）の前に置かれる
        assert document.index("<w:drawing>") < document.index("図の題目")
        assert document.index("表の題目") < document.index("<w:tbl>")
        # 表の後の段落には空きが入る（後処理。表の前・図の前後はスタイルで付く）
        after_table = document[document.index("</w:tbl>") :]
        next_paragraph = after_table[: after_table.index("</w:p>")]
        assert '<w:spacing w:beforeLines="100" />' in next_paragraph

    def test_reports_undefined_reference_as_warning(self, tmp_path: Path) -> None:
        """未定義の参照が警告として返る（--strict が失敗にできる前提の確認）。"""
        pandoc, crossref = TOOLS
        chapters = tmp_path / "chapters"
        _touch(chapters / "01_intro" / "00_chapter.md", "# 第1章\n\n@fig:missing を参照する．\n")
        warnings = target.build_docx(
            chapters, tmp_path / "out.docx", pandoc=pandoc, crossref=crossref
        )
        assert "fig:missing" in warnings

    def test_renders_citations_in_thesis_style(self, tmp_path: Path) -> None:
        """本文の引用は上付きの「1)」、参考文献リストは卒業論文の形式で出力される。

        引用順に番号が振られ、複数の引用は「2)3)」と並び、再掲は同じ番号になる。
        図の参照（@fig:）は citeproc に引用と誤認されない。
        """
        pandoc, crossref = TOOLS
        chapters = tmp_path / "chapters"
        _write_png(tmp_path / "figures" / "a.png")
        _touch(
            chapters / "01_intro" / "00_chapter.md",
            "# 第1章　はじめに\n\n"
            "SMW 法を用いた[@S1]．既往研究に従う[@S12; @S13]．再掲する[@S1]．@fig:a を見る．\n\n"
            "![図の題目](figures/a.png){#fig:a}\n",
        )
        _touch(
            chapters / "90_back" / "02_references.md",
            "# 参考文献\n\n::: {#refs}\n:::\n",
        )
        output = tmp_path / "out.docx"
        warnings = target.build_docx(
            chapters, output, pandoc=pandoc, crossref=crossref, resource_paths=(tmp_path,)
        )
        assert warnings == ""
        assert (tmp_path / target.GENERATED_BIBLIOGRAPHY_NAME).is_file()
        document = _document_xml(output)
        texts = _paragraph_texts(document)
        assert "SMW 法を用いた1)．既往研究に従う2)3)．再掲する1)．図-1 を見る．" in texts
        superscripts = re.findall(
            r'<w:vertAlign w:val="superscript" />.*?<w:t[^>]*>([^<]*)</w:t>', document
        )
        assert superscripts[:3] == ["1)", "2)3)", "1)"]
        assert (
            "1) Ermida, S. L., Soares, P., Mantas, V., Göttsche, F.-M. and Trigo, I. F.："
            "Google Earth Engine Open-Source Code for Land Surface Temperature Estimation"
            " from the Landsat Series，Remote Sensing，Vol.12，No.9，p.1471，2020．"
        ) in texts
        assert any(
            text.startswith("3) Zuur, A. F., Ieno, E. N. and Elphick, C. S.：")
            and text.endswith("Methods in Ecology and Evolution，Vol.1，No.1，pp.3-14，2010．")
            for text in texts
        )
        # 題名は DOI へのハイパーリンクにしない（metadata.yaml の link-bibliography）
        assert "<w:hyperlink" not in document

    def test_latin_symbols_use_latin_font_character_styles(self, tmp_path: Path) -> None:
        """記号は単独のランに分かれ、明朝の文脈は LatinSymbol・ゴシックの文脈は LatinSymbolSans。

        和文フォントの「°」「−」「±」「×」は全角幅で「°C」が空いたり幅が揃わなかったりするため、
        Lua フィルタで欧文フォントの文字スタイルに分ける。本文の段落の文字列は変わらず、
        コードの中の記号は分けない。
        """
        pandoc, crossref = TOOLS
        chapters = tmp_path / "chapters"
        _write_png(tmp_path / "figures" / "a.png")
        body = "気温は 34.0 °C，乾季の（°C）である．差は −0.5，平均 ± 6 倍，3 × 3 画素．"
        _touch(
            chapters / "01_intro" / "00_chapter.md",
            "# 第1章　気温 30 °C\n\n"
            f"{body}`t °C` は分けない．\n\n"
            "| 項目 | 気温（°C） |\n|---|---|\n| LST − 気温 | −20 °C |\n\n"
            ": 表題 °C {#tbl:a}\n\n"
            "![図題 °C](figures/a.png){#fig:a}\n",
        )
        output = tmp_path / "out.docx"
        target.build_docx(
            chapters, output, pandoc=pandoc, crossref=crossref, resource_paths=(tmp_path,)
        )
        document = _document_xml(output)
        assert f"{body}t °C は分けない．" in _paragraph_texts(document)

        symbols = "°−±×"
        styles_by_context: dict[str, list[tuple[str | None, str]]] = {"body": [], "sans": []}
        code_runs = []
        tables = re.findall(r"<w:tbl>.*?</w:tbl>", document, re.S)
        outside_tables = re.sub(r"<w:tbl>.*?</w:tbl>", "", document, flags=re.S)
        contexts = [("sans", table) for table in tables] + [("body", outside_tables)]
        for context, xml in contexts:
            for paragraph in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
                paragraph_style = re.search(r'<w:pStyle w:val="([^"]+)"', paragraph)
                gothic = paragraph_style and paragraph_style.group(1).startswith(
                    ("Heading", "TableCaption", "ImageCaption")
                )
                for run in re.findall(r"<w:r>.*?</w:r>", paragraph, re.S):
                    text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run))
                    if not any(symbol in text for symbol in symbols):
                        continue
                    run_style = re.search(r'<w:rStyle w:val="([^"]+)"', run)
                    run_style = run_style.group(1) if run_style else None
                    if run_style == "VerbatimChar":
                        code_runs.append(text)
                        continue
                    assert text in symbols, f"記号が単独のランに分かれていない: {text!r}"
                    key = "sans" if context == "sans" or gothic else "body"
                    styles_by_context[key].append((run_style, text))
        # 本文の 5 件（°°−±×）
        assert styles_by_context["body"] == [("LatinSymbol", text) for text in "°°−±×"]
        # 見出し・表見出し・表のセル（− と −°）・表題・図題の 7 件（出現順は文書の並び順）
        assert sorted(styles_by_context["sans"]) == sorted(
            ("LatinSymbolSans", text) for text in "°°−−°°°"
        )
        assert code_runs == ["t °C"]

    def test_degree_sign_in_bibliography_uses_serif_style(self, tmp_path: Path) -> None:
        """citeproc が作る参考文献リストの「°」も LatinSymbol に分ける（citeproc の後に適用）。"""
        pandoc, crossref = TOOLS
        chapters = tmp_path / "chapters"
        _touch(chapters / "01_intro" / "00_chapter.md", "# 第1章\n\n引用する[@heat_note]．\n")
        _touch(chapters / "90_back" / "02_references.md", "# 参考文献\n\n::: {#refs}\n:::\n")
        extra = _touch(
            tmp_path / "extra.bib",
            "@misc{heat_note,\n  author = {Doe, John},\n"
            "  title = {Surface heat above 40 °C},\n  year = {2020}\n}\n",
        )
        output = tmp_path / "out.docx"
        warnings = target.build_docx(
            chapters, output, pandoc=pandoc, crossref=crossref, extra_bibliography=extra
        )
        assert warnings == ""
        document = _document_xml(output)
        assert any("Surface heat above 40 °C" in text for text in _paragraph_texts(document))
        degree_runs = [
            run
            for run in re.findall(r"<w:r>.*?</w:r>", document, re.S)
            if "°" in "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run))
        ]
        assert len(degree_runs) == 1
        assert '<w:rStyle w:val="LatinSymbol" />' in degree_runs[0]
        assert re.search(r"<w:t[^>]*>°</w:t>", degree_runs[0])

    def test_reports_unknown_citation_as_warning(self, tmp_path: Path) -> None:
        """文献 DB にも手書きの .bib にも無い引用キーは警告になる（--strict で失敗にできる）。"""
        pandoc, crossref = TOOLS
        chapters = tmp_path / "chapters"
        _touch(chapters / "01_intro" / "00_chapter.md", "# 第1章\n\n引用する[@no_such_key]．\n")
        warnings = target.build_docx(
            chapters, tmp_path / "out.docx", pandoc=pandoc, crossref=crossref
        )
        assert "no_such_key" in warnings
