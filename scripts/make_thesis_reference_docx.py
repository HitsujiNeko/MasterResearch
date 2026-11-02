"""修士論文用の pandoc reference.docx を生成する。

pandoc 既定の reference.docx（``pandoc --print-default-data-file reference.docx``）を土台に、
卒業論文の書式値（用紙・余白・行グリッド・フォント・図表題・表・表紙）を適用して
``thesis/templates/reference.docx`` を書き出す。卒業論文の docx そのものは使わないため、
本文・画像・コメント・変更履歴は混入しない。

書式値の出所は卒業論文の docx（本文の節の ``sectPr``・段落書式・テーマフォント）であり、
値は本ファイルの定数にのみ持つ。書式を変えるときは定数を直して再生成する。

使い方:
    python scripts/make_thesis_reference_docx.py
    python scripts/make_thesis_reference_docx.py --pandoc path/to/pandoc --output out.docx

出力はバイト単位で決定的になるよう、zip の各エントリの日時を固定する
（再生成しても内容が同じなら git の差分が出ない）。
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "thesis" / "templates" / "reference.docx"

# zip エントリの固定日時（決定的な出力のため。zip 形式が表せる最古の日時）
ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)

# --- 書式値（卒業論文から転記） ---
# 長さは twip（1/20 pt、1 mm ≒ 56.7 twip）、文字サイズは半ポイント（21 = 10.5 pt）
FONT_MINCHO = "ＭＳ 明朝"
FONT_GOTHIC = "ＭＳ ゴシック"
FONT_LATIN = "Times New Roman"
FONT_TABLE = "游ゴシック"
SIZE_BODY = 21  # 10.5 pt
SIZE_TABLE = 22  # 11 pt
SIZE_FOOTNOTE = 18  # 9 pt
SIZE_COVER_TITLE = 48  # 24 pt
SIZE_COVER_OTHER = 36  # 18 pt

# A4 縦、余白 上35／下30／左30／右30 mm（卒業論文の本文の節の値）
SECTION_PROPERTIES = (
    "<w:sectPr>"
    '<w:footerReference w:type="default" r:id="rIdThesisFooter1" />'
    '<w:footnotePr><w:numRestart w:val="eachSect" /></w:footnotePr>'
    '<w:pgSz w:w="11906" w:h="16838" w:orient="portrait" />'
    '<w:pgMar w:top="1985" w:right="1701" w:bottom="1701" w:left="1701"'
    ' w:header="851" w:footer="992" w:gutter="0" />'
    '<w:cols w:space="425" />'
    # 行グリッド 18 pt（linePitch は twip）
    '<w:docGrid w:type="lines" w:linePitch="360" />'
    "</w:sectPr>"
)

FOOTER_PART = "word/footer1.xml"
FOOTER_REL_ID = "rIdThesisFooter1"
FOOTER_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"
FOOTER_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"

# フッター中央のページ番号（PAGE フィールド）
FOOTER_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<w:p><w:pPr><w:pStyle w:val="Footer" /><w:jc w:val="center" /></w:pPr>'
    '<w:r><w:fldChar w:fldCharType="begin" /></w:r>'
    '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate" /></w:r>'
    "<w:r><w:t>1</w:t></w:r>"
    '<w:r><w:fldChar w:fldCharType="end" /></w:r>'
    "</w:p></w:ftr>"
)


def _fonts(east_asia: str, latin: str) -> str:
    """和文・欧文フォントを明示する ``w:rFonts`` 要素を返す（テーマフォントは使わない）。"""
    return (
        f'<w:rFonts w:ascii="{latin}" w:hAnsi="{latin}" w:eastAsia="{east_asia}" w:cs="{latin}" />'
    )


def _size(half_points: int) -> str:
    """文字サイズ（半ポイント）の ``w:sz``・``w:szCs`` 要素を返す。"""
    return f'<w:sz w:val="{half_points}" /><w:szCs w:val="{half_points}" />'


# 文書既定の書式。本文フォントは段落スタイルではなくここに置く。表スタイルの書式は
# 段落スタイルより優先度が低いため、本文スタイルにフォントを書くと表内の游ゴシックが効かない
DOC_DEFAULTS = (
    "<w:docDefaults>"
    "<w:rPrDefault><w:rPr>"
    + _fonts(FONT_MINCHO, FONT_LATIN)
    + '<w:kern w:val="2" />'
    + _size(SIZE_BODY)
    + '<w:lang w:val="en-US" w:eastAsia="ja-JP" w:bidi="ar-SA" />'
    "</w:rPr></w:rPrDefault>"
    '<w:pPrDefault><w:pPr><w:spacing w:before="0" w:after="0" /></w:pPr></w:pPrDefault>'
    "</w:docDefaults>"
)


def _paragraph_style(
    style_id: str,
    name: str,
    *,
    based_on: str | None = "Normal",
    next_style: str | None = None,
    ppr: str = "",
    rpr: str = "",
    custom: bool = False,
) -> str:
    """段落スタイルの ``w:style`` 要素を組み立てる。"""
    attrs = ' w:customStyle="1"' if custom else ""
    parts = [
        f'<w:style w:type="paragraph"{attrs} w:styleId="{style_id}">',
        f'<w:name w:val="{name}" />',
    ]
    if based_on:
        parts.append(f'<w:basedOn w:val="{based_on}" />')
    if next_style:
        parts.append(f'<w:next w:val="{next_style}" />')
    parts.append("<w:qFormat />")
    if ppr:
        parts.append(f"<w:pPr>{ppr}</w:pPr>")
    if rpr:
        parts.append(f"<w:rPr>{rpr}</w:rPr>")
    parts.append("</w:style>")
    return "".join(parts)


def _heading_style(level: int) -> str:
    """見出しスタイル（ＭＳ ゴシック 10.5 pt。章見出しのみ改ページ前置）を返す。"""
    page_break = "<w:pageBreakBefore />" if level == 1 else ""
    ppr = (
        f"<w:keepNext /><w:keepLines />{page_break}"
        '<w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto" />'
        f'<w:jc w:val="left" /><w:outlineLvl w:val="{level - 1}" />'
    )
    rpr = _fonts(FONT_GOTHIC, FONT_GOTHIC) + '<w:color w:val="000000" />' + _size(SIZE_BODY)
    return _paragraph_style(
        f"Heading{level}", f"heading {level}", next_style="BodyText", ppr=ppr, rpr=rpr
    )


# 本文段落: 左揃え・行間 1.5 行・字下げ 1 字（卒業論文の本文段落の書式）
BODY_PPR = (
    '<w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto" />'
    '<w:ind w:firstLineChars="100" w:firstLine="210" />'
    '<w:jc w:val="left" />'
)
# 図表題: ＭＳ ゴシック 10.5 pt・中央揃え
CAPTION_PPR = (
    '<w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto" /><w:jc w:val="center" />'
)
CAPTION_RPR = _fonts(FONT_GOTHIC, FONT_GOTHIC) + _size(SIZE_BODY)
COVER_PPR = '<w:jc w:val="center" />'

# 置き換えるスタイル（styleId → w:style 要素）。既定に無いものは末尾に追加する
STYLES: dict[str, str] = {
    "Normal": (
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal" /><w:qFormat />'
        '<w:pPr><w:widowControl w:val="0" /><w:jc w:val="both" /></w:pPr>'
        "</w:style>"
    ),
    "BodyText": _paragraph_style("BodyText", "Body Text", ppr=BODY_PPR),
    "FirstParagraph": _paragraph_style(
        "FirstParagraph", "First Paragraph", based_on="BodyText", next_style="BodyText", custom=True
    ),
    # 箇条書き（タイトなリスト）と表内の段落に使われるため、字下げと行間を戻す
    "Compact": _paragraph_style(
        "Compact",
        "Compact",
        based_on="BodyText",
        ppr=(
            '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto" />'
            '<w:ind w:firstLineChars="0" w:firstLine="0" />'
        ),
        custom=True,
    ),
    # 表紙: 題目 24 pt、副題（「修士論文」）・著者・日付 18 pt
    "Title": _paragraph_style(
        "Title",
        "Title",
        next_style="BodyText",
        ppr=COVER_PPR + '<w:spacing w:before="2400" w:after="600" />',
        rpr=_size(SIZE_COVER_TITLE),
    ),
    "Subtitle": _paragraph_style(
        "Subtitle",
        "Subtitle",
        next_style="BodyText",
        ppr=COVER_PPR + '<w:spacing w:before="0" w:after="1200" />',
        rpr=_size(SIZE_COVER_OTHER),
    ),
    "Author": _paragraph_style(
        "Author",
        "Author",
        next_style="BodyText",
        ppr=COVER_PPR + '<w:spacing w:before="0" w:after="240" />',
        rpr=_size(SIZE_COVER_OTHER),
        custom=True,
    ),
    "Date": _paragraph_style(
        "Date",
        "Date",
        next_style="BodyText",
        ppr=COVER_PPR + '<w:spacing w:before="0" w:after="240" />',
        rpr=_size(SIZE_COVER_OTHER),
    ),
    # 目次見出し（「目次」）: 表紙の後で改ページし、目次自体には載せない
    "TOCHeading": _paragraph_style(
        "TOCHeading",
        "TOC Heading",
        next_style="BodyText",
        ppr=(
            '<w:keepNext /><w:pageBreakBefore /><w:spacing w:before="0" w:after="240" />'
            '<w:jc w:val="center" /><w:outlineLvl w:val="9" />'
        ),
        rpr=_fonts(FONT_GOTHIC, FONT_GOTHIC) + _size(SIZE_BODY),
    ),
    **{f"Heading{level}": _heading_style(level) for level in range(1, 10)},
    "Caption": _paragraph_style("Caption", "Caption", ppr=CAPTION_PPR, rpr=CAPTION_RPR),
    # 表題は表の上（pandoc の出力順）。表と離れないよう次段落と同じページに置く
    "TableCaption": _paragraph_style(
        "TableCaption", "Table Caption", based_on="Caption", ppr="<w:keepNext />", custom=True
    ),
    "ImageCaption": _paragraph_style(
        "ImageCaption", "Image Caption", based_on="Caption", custom=True
    ),
    # 図の段落: 中央揃え。図と図題（図の下）が離れないよう次段落と同じページに置く
    "Figure": _paragraph_style("Figure", "Figure", ppr='<w:jc w:val="center" />', custom=True),
    "CaptionedFigure": _paragraph_style(
        "CaptionedFigure",
        "Captioned Figure",
        based_on="Figure",
        ppr='<w:keepNext /><w:jc w:val="center" />',
        custom=True,
    ),
    "FootnoteText": _paragraph_style(
        "FootnoteText",
        "footnote text",
        next_style="FootnoteText",
        rpr=_size(SIZE_FOOTNOTE),
    ),
    # 表: 中央寄せ・格子罫線・表内は游ゴシック 11 pt
    "Table": (
        '<w:style w:type="table" w:default="1" w:styleId="Table">'
        '<w:name w:val="Table" /><w:basedOn w:val="TableNormal" /><w:qFormat />'
        "<w:rPr>" + _fonts(FONT_TABLE, FONT_TABLE) + _size(SIZE_TABLE) + "</w:rPr>"
        "<w:tblPr>"
        '<w:jc w:val="center" />'
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="000000" />'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="000000" />'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000" />'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="000000" />'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000" />'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000" />'
        "</w:tblBorders>"
        "<w:tblCellMar>"
        '<w:left w:w="99" w:type="dxa" /><w:right w:w="99" w:type="dxa" />'
        "</w:tblCellMar>"
        "</w:tblPr>"
        "</w:style>"
    ),
    "Footer": _paragraph_style("Footer", "footer", ppr='<w:jc w:val="center" />'),
}


def find_pandoc() -> str:
    """pandoc を PATH から、無ければ実行中の Python と同じ conda 環境から探す。

    conda 環境の Python をフルパスで呼ぶと PATH に環境の bin が入らないため、
    ``Library/bin``（Windows）・``bin`` も探す。見つからなければ ``"pandoc"`` を返し、
    実行時のエラーとして報告させる。
    """
    found = shutil.which("pandoc")
    if found:
        return found
    prefix = Path(sys.prefix)
    for directory in (prefix / "Library" / "bin", prefix / "bin"):
        found = shutil.which("pandoc", path=str(directory))
        if found:
            return found
    return "pandoc"


def load_default_reference(pandoc: str) -> bytes:
    """pandoc 既定の reference.docx のバイト列を取得する。

    Args:
        pandoc: pandoc の実行ファイル名またはパス。

    Returns:
        既定の reference.docx のバイト列。

    Raises:
        subprocess.CalledProcessError: pandoc が異常終了した場合。
        FileNotFoundError: pandoc が見つからない場合。
    """
    # 「-o -」は Windows で標準出力ではなく「-」という名前のファイルになるため、
    # 一時ディレクトリに書き出して読み戻す
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "reference.docx"
        subprocess.run(
            [pandoc, "-o", str(path), "--print-default-data-file", "reference.docx"],
            check=True,
            capture_output=True,
        )
        return path.read_bytes()


def _style_pattern(style_id: str) -> re.Pattern[str]:
    """指定した styleId の ``w:style`` 要素全体に一致する正規表現を返す。"""
    return re.compile(
        r'<w:style\b[^>]*\bw:styleId="' + re.escape(style_id) + r'"[^>]*>.*?</w:style>',
        re.S,
    )


def replace_or_append_style(styles_xml: str, style_id: str, style_xml: str) -> str:
    """styles.xml の指定スタイルを置き換える。存在しなければ末尾に追加する。

    Args:
        styles_xml: styles.xml の文字列。
        style_id: 対象の styleId。
        style_xml: 新しい ``w:style`` 要素。

    Returns:
        置き換え後の styles.xml。

    Raises:
        ValueError: 同じ styleId のスタイルが複数ある場合（置き換え先が一意に決まらない）。
    """
    pattern = _style_pattern(style_id)
    matches = pattern.findall(styles_xml)
    if len(matches) > 1:
        raise ValueError(f"styleId が重複しています: {style_id}")
    if matches:
        return pattern.sub(lambda _: style_xml, styles_xml)
    return styles_xml.replace("</w:styles>", style_xml + "</w:styles>")


def build_styles_xml(styles_xml: str) -> str:
    """既定の styles.xml に文書既定書式と論文用スタイルを適用する。

    Raises:
        ValueError: 文書既定書式（``w:docDefaults``）が見つからない場合。
    """
    pattern = re.compile(r"<w:docDefaults>.*?</w:docDefaults>", re.S)
    if not pattern.search(styles_xml):
        raise ValueError("styles.xml に w:docDefaults がありません")
    styles_xml = pattern.sub(lambda _: DOC_DEFAULTS, styles_xml, count=1)
    for style_id, style_xml in STYLES.items():
        styles_xml = replace_or_append_style(styles_xml, style_id, style_xml)
    return styles_xml


def build_document_xml(document_xml: str) -> str:
    """document.xml の末尾の節設定（用紙・余白・行グリッド・フッター）を置き換える。

    Raises:
        ValueError: 節設定（``w:sectPr``）が見つからない場合。
    """
    pattern = re.compile(r"<w:sectPr\b[^>]*>.*?</w:sectPr>", re.S)
    matches = list(pattern.finditer(document_xml))
    if not matches:
        raise ValueError("document.xml に w:sectPr がありません")
    last = matches[-1]
    return document_xml[: last.start()] + SECTION_PROPERTIES + document_xml[last.end() :]


def add_footer_relationship(rels_xml: str) -> str:
    """document.xml.rels にフッターへの参照を追加する（既にあれば変更しない）。"""
    if f'Id="{FOOTER_REL_ID}"' in rels_xml:
        return rels_xml
    rel = f'<Relationship Type="{FOOTER_REL_TYPE}" Id="{FOOTER_REL_ID}" Target="footer1.xml" />'
    return rels_xml.replace("</Relationships>", rel + "</Relationships>")


def add_footer_content_type(content_types_xml: str) -> str:
    """[Content_Types].xml にフッター部品の型を追加する（既にあれば変更しない）。"""
    if f'PartName="/{FOOTER_PART}"' in content_types_xml:
        return content_types_xml
    override = f'<Override PartName="/{FOOTER_PART}" ContentType="{FOOTER_CONTENT_TYPE}" />'
    return content_types_xml.replace("</Types>", override + "</Types>")


def build_reference_parts(default_parts: dict[str, bytes]) -> dict[str, bytes]:
    """既定の reference.docx の部品に論文用の書式を適用した部品を返す。

    Args:
        default_parts: 部品名 → 内容のバイト列（既定の reference.docx の全エントリ）。

    Returns:
        書式を適用した部品（入力の順序を保ち、フッター部品を末尾に加える）。
    """
    parts = dict(default_parts)

    def edit(name: str, func) -> None:
        parts[name] = func(parts[name].decode("utf-8")).encode("utf-8")

    edit("word/styles.xml", build_styles_xml)
    edit("word/document.xml", build_document_xml)
    edit("word/_rels/document.xml.rels", add_footer_relationship)
    edit("[Content_Types].xml", add_footer_content_type)
    parts[FOOTER_PART] = FOOTER_XML.encode("utf-8")
    return parts


def read_docx_parts(data: bytes) -> dict[str, bytes]:
    """docx（zip）のバイト列から部品名 → 内容の辞書を読み出す（エントリ順を保つ）。"""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def write_docx(parts: dict[str, bytes], output: Path) -> None:
    """部品を docx（zip）として書き出す。エントリの日時を固定し、出力を決定的にする。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(description="修士論文用の pandoc reference.docx を生成する")
    parser.add_argument(
        "--pandoc",
        default=None,
        help="pandoc の実行ファイル（既定: PATH か実行中の conda 環境から探す）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="出力先（既定: thesis/templates/reference.docx）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """reference.docx を生成する。終了コードを返す（0: 成功、2: 失敗）。"""
    args = parse_args(argv)
    try:
        default_bytes = load_default_reference(args.pandoc or find_pandoc())
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"pandoc から既定の reference.docx を取得できません: {exc}", file=sys.stderr)
        return 2
    parts = build_reference_parts(read_docx_parts(default_bytes))
    write_docx(parts, args.output)
    print(f"生成しました: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
