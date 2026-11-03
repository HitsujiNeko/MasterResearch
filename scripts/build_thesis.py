"""修士論文の md から docx を生成する（1 コマンドビルド）。

``thesis/chapters/`` 配下の md を相対パスの昇順で結合し、pandoc と pandoc-crossref で
``thesis/build/thesis.docx`` を生成する。書式は ``thesis/templates/reference.docx``、
題目・目次・図表番号の設定は ``thesis/metadata.yaml`` に従う。

本文中の引用（``[@S1]`` 等）は pandoc の citeproc で処理する。ビルドのたびに文献 DB から
``.bib`` を生成し（``scripts/make_thesis_bib.py``。出力 docx と同じディレクトリの
``references.bib``）、文献 DB 未登録の文献を手書きした ``thesis/references/extra.bib`` と
合わせて渡す。書式は ``thesis/templates/thesis-ja.csl``（卒業論文に準拠した番号順）に従う。

``--pdf`` を付けると、Word（COM）で docx を開いて目次と相互参照を更新し、docx を上書き
保存したうえで PDF も書き出す（目視確認用。Windows かつ Word がある環境のみ）。pandoc が
出力する目次は Word のフィールドであり、Word で更新するまでページ番号が入らないため。

使い方:
    python scripts/build_thesis.py
    python scripts/build_thesis.py --pdf
    python scripts/build_thesis.py --output path/to/out.docx

pandoc・pandoc-crossref は PATH 上か、実行中の Python と同じ conda 環境
（``Library/bin`` 等）から探す。
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
THESIS_DIR = REPO_ROOT / "thesis"
CHAPTERS_DIR = THESIS_DIR / "chapters"
METADATA_FILE = THESIS_DIR / "metadata.yaml"
REFERENCE_DOCX = THESIS_DIR / "templates" / "reference.docx"
CSL_FILE = THESIS_DIR / "templates" / "thesis-ja.csl"
EXTRA_BIBLIOGRAPHY = THESIS_DIR / "references" / "extra.bib"
# 文献 DB から生成する .bib のファイル名（出力 docx と同じディレクトリに置く）
GENERATED_BIBLIOGRAPHY_NAME = "references.bib"
DEFAULT_OUTPUT = THESIS_DIR / "build" / "thesis.docx"

# 目次に載せる見出しの深さ（章・節・項）
TOC_DEPTH = 3

# Word（COM）の操作の上限秒数。Word がダイアログで止まった場合にビルドを打ち切るため
WORD_TIMEOUT_SECONDS = 300

# pandoc（pandoc-crossref フィルタを含む）の実行の上限秒数。応答しない場合に打ち切るため
PANDOC_TIMEOUT_SECONDS = 300

# 文献 DB の論文の引用キー（S 番号）の形。手書きの .bib では使わない
RESERVED_KEY_PATTERN = re.compile(r"^S\d+$")
# .bib のエントリの型と引用キー（@comment 等の非エントリは後で除く）。
# BibTeX は「@book{key,」と「@book(key,」の両方を受け付ける
BIB_ENTRY_PATTERN = re.compile(r"^[ \t]*@([A-Za-z]+)[ \t]*[{(][ \t]*([^,\s]+)[ \t]*,", re.MULTILINE)
BIB_NON_ENTRY_TYPES = {"comment", "string", "preamble"}

# 終了コード
EXIT_OK = 0
EXIT_ERROR = 2

# Word COM で目次・フィールドを更新し、docx を保存して PDF を書き出す PowerShell スクリプト。
# パスは引用符の扱いを避けるため環境変数で渡す。17 は wdExportFormatPDF
WORD_EXPORT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($env:THESIS_DOCX, $false, $false)
    try {
        $doc.Fields.Update() | Out-Null
        foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
        $doc.Save()
        $doc.ExportAsFixedFormat($env:THESIS_PDF, 17)
    } finally {
        $doc.Close($false)
    }
} finally {
    $word.Quit()
}
"""


def _load_bib_module() -> ModuleType:
    """同じディレクトリの make_thesis_bib.py を読み込む（scripts/ はパッケージでないため）。"""
    name = "make_thesis_bib"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


make_thesis_bib = _load_bib_module()


def collect_chapter_files(chapters_dir: Path) -> list[Path]:
    """章・節の md ファイルを結合順（相対パスの昇順）で返す。

    Args:
        chapters_dir: 章ディレクトリを並べた親ディレクトリ。

    Returns:
        md ファイルのパスの一覧。

    Raises:
        FileNotFoundError: ディレクトリが無い、または md が 1 つも無い場合。
    """
    if not chapters_dir.is_dir():
        raise FileNotFoundError(f"章のディレクトリがありません: {chapters_dir}")
    files = sorted(
        (path for path in chapters_dir.rglob("*.md") if path.is_file()),
        key=lambda path: path.relative_to(chapters_dir).parts,
    )
    if not files:
        raise FileNotFoundError(f"md ファイルがありません: {chapters_dir}")
    return files


def find_executable(name: str, explicit: str | None = None) -> str:
    """実行ファイルのパスを探す。

    明示指定があればそれを、無ければ PATH を、それでも無ければ実行中の Python と同じ
    conda 環境の ``Library/bin``（Windows）・``bin`` を探す。conda 環境の Python を
    フルパスで呼ぶと、PATH に環境の bin が入らないため。

    Args:
        name: 実行ファイル名（拡張子なし）。
        explicit: 利用者が指定したパス（指定時は存在確認のみ）。

    Returns:
        実行ファイルのパス。

    Raises:
        FileNotFoundError: 見つからない場合。
    """
    if explicit:
        found = shutil.which(explicit)
        if found is None:
            raise FileNotFoundError(f"{name} が見つかりません: {explicit}")
        return found
    found = shutil.which(name)
    if found:
        return found
    prefix = Path(sys.prefix)
    for directory in (prefix / "Library" / "bin", prefix / "bin", prefix / "Scripts"):
        found = shutil.which(name, path=str(directory))
        if found:
            return found
    raise FileNotFoundError(
        f"{name} が見つかりません。conda 環境 masterresearch の Python で実行するか、"
        "環境に依存を入れてください（conda env update -n masterresearch -f environment.yml）"
    )


def bibliography_keys(text: str) -> list[str]:
    """.bib の本文から引用キーを出現順に取り出す（@comment 等は除く）。

    Args:
        text: .bib の本文（先頭の BOM は無視する）。

    Returns:
        引用キーの一覧（重複を含む）。
    """
    return [
        key
        for entry_type, key in BIB_ENTRY_PATTERN.findall(text.removeprefix("﻿"))
        if entry_type.lower() not in BIB_NON_ENTRY_TYPES
    ]


def check_extra_bibliography(extra_text: str) -> None:
    """手書きの .bib の引用キーが、文献 DB の論文・手書き分の中で衝突しないことを確かめる。

    文献 DB から生成する .bib の引用キーはすべて S 番号の形のため、手書き分で S 番号の形を
    禁じれば生成分との衝突も防げる。

    Args:
        extra_text: 手書きの .bib の本文。

    Raises:
        make_thesis_bib.BibliographyError: S 番号の形のキー・重複キーがある場合。
    """
    extra_keys = bibliography_keys(extra_text)
    problems = [
        f"{key}: 手書きの .bib では S 番号の形のキーを使わない（文献 DB の論文用）"
        for key in extra_keys
        if RESERVED_KEY_PATTERN.match(key)
    ]
    seen: set[str] = set()
    for key in extra_keys:
        if key in seen:
            problems.append(f"{key}: 手書きの .bib で引用キーが重複しています")
        seen.add(key)
    if problems:
        raise make_thesis_bib.BibliographyError(problems)


def build_pandoc_command(
    pandoc: str,
    crossref: str,
    inputs: Sequence[Path],
    output: Path,
    metadata_file: Path,
    reference_docx: Path,
    resource_paths: Sequence[Path],
    bibliographies: Sequence[Path],
    csl_file: Path,
) -> list[str]:
    """md → docx の pandoc コマンドを組み立てる。

    pandoc-crossref は citeproc より先に適用する（``@fig:`` 等を引用と誤認させないため）。

    Args:
        pandoc: pandoc のパス。
        crossref: pandoc-crossref のパス（フィルタとして渡す）。
        inputs: 結合する md（この順に結合される）。
        output: 出力する docx。
        metadata_file: 題目・目次・crossref 設定の YAML。
        reference_docx: 書式の雛形。
        resource_paths: 図のパスを解決する基準ディレクトリ（先頭から順に探す）。
        bibliographies: 引用に使う .bib（文献 DB の生成分と手書き分）。
        csl_file: 引用・参考文献の書式（CSL）。

    Returns:
        subprocess に渡す引数リスト。
    """
    return [
        pandoc,
        *(str(path) for path in inputs),
        "--from=markdown",
        "--to=docx",
        f"--filter={crossref}",
        "--citeproc",
        *(f"--bibliography={path}" for path in bibliographies),
        f"--csl={csl_file}",
        f"--metadata-file={metadata_file}",
        f"--reference-doc={reference_docx}",
        "--toc",
        f"--toc-depth={TOC_DEPTH}",
        f"--resource-path={os.pathsep.join(str(path) for path in resource_paths)}",
        f"--output={output}",
    ]


def build_docx(
    chapters_dir: Path,
    output: Path,
    *,
    pandoc: str,
    crossref: str,
    metadata_file: Path = METADATA_FILE,
    reference_docx: Path = REFERENCE_DOCX,
    resource_paths: Sequence[Path] = (THESIS_DIR, REPO_ROOT),
    csl_file: Path = CSL_FILE,
    extra_bibliography: Path = EXTRA_BIBLIOGRAPHY,
) -> str:
    """章・節の md を結合して docx を生成する。

    図のパスは ``thesis/`` からの相対（``figures/...``）か、リポジトリルートからの相対
    （``images/...``）で書ける（``resource_paths`` の既定値）。文献 DB から生成する .bib は
    出力 docx と同じディレクトリの ``references.bib`` に書き出す（同名のファイルは上書きする）。

    Returns:
        pandoc・pandoc-crossref の標準エラー（警告。無ければ空文字列）。

    Raises:
        FileNotFoundError: 入力が無い場合。
        make_thesis_bib.BibliographyError: 文献 DB と引用用書誌が整合しない場合、手書きの
            .bib の引用キーが衝突する場合。
        subprocess.CalledProcessError: pandoc が異常終了した場合（標準エラーを含む）。
        subprocess.TimeoutExpired: pandoc の実行が上限秒数を超えた場合。
    """
    for path in (metadata_file, reference_docx, csl_file, extra_bibliography):
        if not path.is_file():
            raise FileNotFoundError(f"ファイルがありません: {path}")
    inputs = collect_chapter_files(chapters_dir)
    check_extra_bibliography(extra_bibliography.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    generated_bibliography = output.parent / GENERATED_BIBLIOGRAPHY_NAME
    make_thesis_bib.write_bibtex(generated_bibliography)
    command = build_pandoc_command(
        pandoc,
        crossref,
        inputs,
        output,
        metadata_file,
        reference_docx,
        resource_paths,
        (generated_bibliography, extra_bibliography),
        csl_file,
    )
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=PANDOC_TIMEOUT_SECONDS,
    )
    return result.stderr


def export_pdf_with_word(docx: Path, pdf: Path) -> None:
    """Word（COM）で docx の目次・フィールドを更新して保存し、PDF を書き出す。

    Raises:
        RuntimeError: Windows 以外で呼ばれた場合。
        subprocess.CalledProcessError: Word の操作に失敗した場合。
        subprocess.TimeoutExpired: Word の操作が上限秒数を超えた場合（ダイアログ待ち等）。
    """
    if sys.platform != "win32":
        raise RuntimeError("--pdf は Windows（Word がある環境）でのみ使えます")
    env = {**os.environ, "THESIS_DOCX": str(docx.resolve()), "THESIS_PDF": str(pdf.resolve())}
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", WORD_EXPORT_SCRIPT],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=WORD_TIMEOUT_SECONDS,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(description="修士論文の md から docx を生成する")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="出力する docx（既定: thesis/build/thesis.docx）",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Word で目次を更新して docx を保存し、同名の PDF も書き出す（Windows のみ）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "pandoc・pandoc-crossref が警告（図の欠落・未定義の参照・存在しない引用キー等）を"
            "出したら失敗にする"
        ),
    )
    parser.add_argument("--pandoc", default=None, help="pandoc の実行ファイル")
    parser.add_argument("--pandoc-crossref", default=None, help="pandoc-crossref の実行ファイル")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """論文をビルドする。終了コードを返す（0: 成功、2: 失敗）。"""
    args = parse_args(argv)
    try:
        pandoc = find_executable("pandoc", args.pandoc)
        crossref = find_executable("pandoc-crossref", args.pandoc_crossref)
        warnings = build_docx(CHAPTERS_DIR, args.output, pandoc=pandoc, crossref=crossref)
        if warnings:
            # 図の欠落・参照先の無いラベル等の警告。docx は生成されている
            print(warnings, file=sys.stderr)
            if args.strict:
                print("エラー: 警告があるため失敗とします（--strict）", file=sys.stderr)
                return EXIT_ERROR
        print(f"docx を生成しました: {args.output}")
        if args.pdf:
            pdf = args.output.with_suffix(".pdf")
            export_pdf_with_word(args.output, pdf)
            print(f"目次を更新し、PDF を書き出しました: {pdf}")
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except make_thesis_bib.BibliographyError as exc:
        print("エラー: 参考文献の .bib を用意できません", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_ERROR
    except subprocess.TimeoutExpired as exc:
        if exc.cmd[0] != "powershell":
            message = f"エラー: {exc.cmd[0]} が {exc.timeout:g} 秒を超えたため打ち切りました"
            print(message, file=sys.stderr)
            return EXIT_ERROR
        message = f"エラー: Word の操作が {exc.timeout:g} 秒を超えたため打ち切りました"
        print(message, file=sys.stderr)
        hint = (
            "見えない状態の Word が残って docx を開いたままの場合がある。タスクマネージャーで"
            "WINWORD.EXE を終了してから再実行してください"
        )
        print(hint, file=sys.stderr)
        return EXIT_ERROR
    except subprocess.CalledProcessError as exc:
        message = f"エラー: {exc.cmd[0]} が失敗しました（終了コード {exc.returncode}）"
        print(message, file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _configure_utf8_output() -> None:
    """標準出力・標準エラーを UTF-8 にする（Windows で cp932 になり文字化けするのを防ぐ）。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    _configure_utf8_output()
    sys.exit(main())
