"""scripts/make_thesis_reference_docx.py（論文用 reference.docx の生成）のテスト。

対象は ``src`` パッケージ外のスクリプトのため、ファイルパスを指定して読み込む。
XML 変換の単体テストに加え、追跡している ``thesis/templates/reference.docx`` が卒業論文の
書式値を満たすこと、pandoc がある環境では再生成結果と一致すること（生成スクリプトとの
同期）を確認する。
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "make_thesis_reference_docx.py"
TEMPLATE_PATH = REPO_ROOT / "thesis" / "templates" / "reference.docx"


def _load_target() -> ModuleType:
    """対象スクリプトをモジュールとして読み込む。"""
    spec = importlib.util.spec_from_file_location("make_thesis_reference_docx", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


target = _load_target()


PANDOC = target.find_pandoc()


def _pinned_pandoc_version() -> str | None:
    """environment.yml で固定した pandoc の版を返す（見つからなければ None）。"""
    text = (REPO_ROOT / "environment.yml").read_text(encoding="utf-8")
    match = re.search(r"^\s*-\s*pandoc=([0-9.]+)\s*$", text, re.M)
    return match.group(1) if match else None


def _has_pinned_pandoc() -> bool:
    """固定した版の pandoc が使えるか（版が違うと既定の雛形が変わり一致比較が成り立たない）。"""
    if shutil.which(PANDOC) is None:
        return False
    result = subprocess.run([PANDOC, "--version"], capture_output=True, text=True, check=False)
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    return first_line == f"pandoc {_pinned_pandoc_version()}"


requires_pandoc = pytest.mark.skipif(
    not _has_pinned_pandoc(), reason="environment.yml で固定した版の pandoc が必要"
)


def _read_part(path: Path, name: str) -> str:
    """docx の部品を文字列で読む。"""
    with zipfile.ZipFile(path) as archive:
        return archive.read(name).decode("utf-8")


def _style(styles_xml: str, style_id: str) -> str:
    """styles.xml から指定 styleId の ``w:style`` 要素を取り出す。"""
    match = re.search(
        r'<w:style\b[^>]*w:styleId="' + re.escape(style_id) + r'"[^>]*>.*?</w:style>',
        styles_xml,
        re.S,
    )
    assert match, f"スタイルがありません: {style_id}"
    return match.group(0)


class TestReplaceOrAppendStyle:
    """スタイル要素の置き換え・追加のテスト。"""

    STYLES = (
        '<w:styles><w:style w:type="paragraph" w:styleId="A"><w:name w:val="a" /></w:style>'
        "</w:styles>"
    )

    def test_replaces_existing_style(self) -> None:
        new = '<w:style w:type="paragraph" w:styleId="A"><w:name w:val="new" /></w:style>'
        result = target.replace_or_append_style(self.STYLES, "A", new)
        assert result.count('w:styleId="A"') == 1
        assert '<w:name w:val="new" />' in result

    def test_appends_missing_style(self) -> None:
        new = '<w:style w:type="paragraph" w:styleId="B"><w:name w:val="b" /></w:style>'
        result = target.replace_or_append_style(self.STYLES, "B", new)
        assert result.endswith(new + "</w:styles>")
        assert 'w:styleId="A"' in result

    def test_does_not_match_prefix_of_other_id(self) -> None:
        """Heading1 の置き換えが Heading1Char 等に及ばない。"""
        styles = self.STYLES.replace('w:styleId="A"', 'w:styleId="A1"')
        new = '<w:style w:type="paragraph" w:styleId="A"><w:name w:val="new" /></w:style>'
        result = target.replace_or_append_style(styles, "A", new)
        assert 'w:styleId="A1"' in result
        assert result.endswith(new + "</w:styles>")

    def test_rejects_duplicate_style_id(self) -> None:
        styles = self.STYLES.replace("</w:styles>", self.STYLES[len("<w:styles>") :])
        with pytest.raises(ValueError, match="重複"):
            target.replace_or_append_style(styles, "A", "<w:style />")


class TestBuildParts:
    """styles.xml・document.xml・関係ファイルの変換のテスト。"""

    def test_build_styles_xml_requires_doc_defaults(self) -> None:
        with pytest.raises(ValueError, match="docDefaults"):
            target.build_styles_xml("<w:styles></w:styles>")

    def test_build_document_xml_replaces_last_sect_pr(self) -> None:
        document = (
            "<w:body><w:p><w:pPr><w:sectPr><w:pgSz /></w:sectPr></w:pPr></w:p>"
            '<w:sectPr><w:pgSz w:w="1" /></w:sectPr></w:body>'
        )
        result = target.build_document_xml(document)
        assert result.startswith("<w:body><w:p><w:pPr><w:sectPr><w:pgSz /></w:sectPr>")
        assert result.endswith(target.SECTION_PROPERTIES + "</w:body>")

    def test_build_document_xml_requires_sect_pr(self) -> None:
        with pytest.raises(ValueError, match="sectPr"):
            target.build_document_xml("<w:body></w:body>")

    def test_footer_relationship_is_idempotent(self) -> None:
        rels = "<Relationships></Relationships>"
        once = target.add_footer_relationship(rels)
        assert target.add_footer_relationship(once) == once
        assert once.count(target.FOOTER_REL_ID) == 1

    def test_footer_content_type_is_idempotent(self) -> None:
        types = "<Types></Types>"
        once = target.add_footer_content_type(types)
        assert target.add_footer_content_type(once) == once
        assert once.count("/word/footer1.xml") == 1

    def test_write_docx_is_deterministic(self, tmp_path: Path) -> None:
        parts = {"a.xml": b"<a />", "b/c.xml": b"<c />"}
        first, second = tmp_path / "1.docx", tmp_path / "2.docx"
        target.write_docx(parts, first)
        target.write_docx(parts, second)
        assert first.read_bytes() == second.read_bytes()
        assert target.read_docx_parts(first.read_bytes()) == parts
        # 作成 OS を固定し、Windows 以外で再生成してもバイト列が変わらないようにする
        with zipfile.ZipFile(first) as archive:
            assert {info.create_system for info in archive.infolist()} == {0}


# OOXML（ECMA-376）の CT_PPrBase における段落書式の子要素の順序（本スクリプトが使う要素のみ）
PPR_ORDER = (
    "keepNext",
    "keepLines",
    "pageBreakBefore",
    "widowControl",
    "spacing",
    "ind",
    "jc",
    "outlineLvl",
)


@pytest.mark.parametrize("style_id", sorted(target.STYLES))
def test_paragraph_properties_follow_schema_order(style_id: str) -> None:
    """各スタイルの w:pPr の子要素が OOXML の順序どおりに並ぶ（処理系による無視を防ぐ）。"""
    match = re.search(r"<w:pPr>(.*?)</w:pPr>", target.STYLES[style_id], re.S)
    if match is None:
        return
    names = re.findall(r"<w:(\w+)", match.group(1))
    assert set(names) <= set(PPR_ORDER), f"順序表に無い要素: {set(names) - set(PPR_ORDER)}"
    positions = [PPR_ORDER.index(name) for name in names]
    assert positions == sorted(positions), f"{style_id}: {names}"


class TestCommittedTemplate:
    """追跡している reference.docx が卒業論文の書式値を満たすことのテスト。"""

    def test_page_size_margins_and_grid(self) -> None:
        document = _read_part(TEMPLATE_PATH, "word/document.xml")
        # A4 縦
        assert '<w:pgSz w:w="11906" w:h="16838"' in document
        # 余白 上35／右30／下30／左30 mm（twip）
        assert 'w:top="1985" w:right="1701" w:bottom="1701" w:left="1701"' in document
        # 行グリッド 18 pt
        assert '<w:docGrid w:type="lines" w:linePitch="360" />' in document

    def test_body_font_is_mincho_and_times_10_5pt(self) -> None:
        styles = _read_part(TEMPLATE_PATH, "word/styles.xml")
        defaults = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S).group(0)
        assert 'w:eastAsia="ＭＳ 明朝"' in defaults
        assert 'w:ascii="Times New Roman"' in defaults
        assert '<w:sz w:val="21" />' in defaults
        # 本文スタイルにフォントを書くと表スタイルの游ゴシックが効かなくなるため、置かない
        assert "<w:rFonts" not in _style(styles, "BodyText")

    def test_body_paragraph_layout(self) -> None:
        body = _style(_read_part(TEMPLATE_PATH, "word/styles.xml"), "BodyText")
        assert 'w:line="360" w:lineRule="auto"' in body  # 行間 1.5 行
        assert 'w:firstLineChars="100"' in body  # 字下げ 1 字

    def test_headings_are_gothic_and_chapter_breaks_page(self) -> None:
        styles = _read_part(TEMPLATE_PATH, "word/styles.xml")
        for level in (1, 2, 3):
            heading = _style(styles, f"Heading{level}")
            assert 'w:eastAsia="ＭＳ ゴシック"' in heading
            assert '<w:sz w:val="21" />' in heading
            assert ("<w:pageBreakBefore />" in heading) is (level == 1)

    def test_section_headings_have_space_before(self) -> None:
        """節・項の見出しは段落前に 1 行の空きを持ち、改ページする章見出しは持たない。"""
        styles = _read_part(TEMPLATE_PATH, "word/styles.xml")
        assert "w:beforeLines" not in _style(styles, "Heading1")
        for level in range(2, 10):
            heading = _style(styles, f"Heading{level}")
            assert 'w:beforeLines="100"' in heading, f"Heading{level}"

    def test_captions_and_table(self) -> None:
        styles = _read_part(TEMPLATE_PATH, "word/styles.xml")
        assert 'w:eastAsia="ＭＳ ゴシック"' in _style(styles, "Caption")
        # 表題は表の上に出るため、表と同じページに置く
        assert "<w:keepNext />" in _style(styles, "TableCaption")
        table = _style(styles, "Table")
        assert 'w:eastAsia="游ゴシック"' in table
        assert '<w:sz w:val="22" />' in table
        assert "<w:tblBorders>" in table

    def test_cover_sizes(self) -> None:
        styles = _read_part(TEMPLATE_PATH, "word/styles.xml")
        assert '<w:sz w:val="48" />' in _style(styles, "Title")
        for style_id in ("Subtitle", "Author", "Date"):
            assert '<w:sz w:val="36" />' in _style(styles, style_id)

    def test_footer_page_number_is_wired(self) -> None:
        assert "PAGE" in _read_part(TEMPLATE_PATH, "word/footer1.xml")
        document = _read_part(TEMPLATE_PATH, "word/document.xml")
        rels = _read_part(TEMPLATE_PATH, "word/_rels/document.xml.rels")
        assert f'r:id="{target.FOOTER_REL_ID}"' in document
        assert f'Id="{target.FOOTER_REL_ID}"' in rels

    def test_contains_no_media(self) -> None:
        """卒業論文の画像等が混入していない（スタイルのみの雛形である）。"""
        with zipfile.ZipFile(TEMPLATE_PATH) as archive:
            assert not [name for name in archive.namelist() if name.startswith("word/media")]


@requires_pandoc
def test_committed_template_matches_regenerated(tmp_path: Path) -> None:
    """追跡している reference.docx が生成スクリプトの出力と一致する（定数の変更漏れの検出）。"""
    output = tmp_path / "reference.docx"
    assert target.main(["--pandoc", PANDOC, "--output", str(output)]) == 0
    assert output.read_bytes() == TEMPLATE_PATH.read_bytes(), (
        "生成結果が追跡中の雛形と異なる。生成スクリプトの定数を変えたら再生成してコミットする。"
        "pandoc の版が environment.yml の固定と違う場合も既定の雛形が変わり不一致になる"
    )


def test_main_returns_2_when_default_template_is_unexpected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """既定の雛形の構造が想定と違う（styles.xml が無い等）場合は 2 を返し、書き出さない。"""
    target.write_docx({"word/document.xml": b"<w:body />"}, tmp_path / "broken.docx")
    broken = (tmp_path / "broken.docx").read_bytes()
    monkeypatch.setattr(target, "load_default_reference", lambda pandoc: broken)
    output = tmp_path / "reference.docx"
    assert target.main(["--pandoc", "pandoc", "--output", str(output)]) == 2
    assert not output.exists()


def test_main_returns_2_when_pandoc_missing(tmp_path: Path) -> None:
    output = tmp_path / "reference.docx"
    assert target.main(["--pandoc", str(tmp_path / "no_pandoc"), "--output", str(output)]) == 2
    assert not output.exists()
