"""文献探索（引用スノーボーリング）の月次報告コメントを生成するスクリプト。

[paper_scout](paper_scout.py) で未登録の文献候補を探索し、**報告 Issue の過去のコメントで
提示済みの候補を除いた**上位候補を、Issue コメント用の Markdown として書き出す。
`/paper-scout` スキルの「月次自動実行モード」から呼ばれる。

提示済みかどうかの判定:

- 各コメントの末尾に不可視のマーカー ``<!-- paper-scout-presented: キー キー ... -->`` を埋め込み、
  次回以降はこのマーカーから提示済みのキーを復元する（報告 Issue 自体を正本とし、
  ローカルに状態ファイルを持たない）
- キーは正規化 DOI（``doi:10.xxxx/...``）、DOI が無い候補は OpenAlex ID（``openalex:W...``）
- マーカーに記録するのは、実際に表に載せた候補だけ

本スクリプトは GitHub に書き込まない。既存コメントの取得（``gh api``）と投稿
（``gh issue comment``）はスキルの手順で行う。

終了コード:

- 0: コメント本文を書き出した
- 1: 既存コメントを読めない（保存ファイルが空・JSON 配列でない）、または探索に失敗した
  （候補を1件も取得できなかった。起点を解決できない・OpenAlex 不通など）
- 3: 新規候補が無い（コメント本文は書き出さない）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import quote, unquote

from src.common.paths import prepare_output_path, resolve_existing_path
from src.literature import openalex, paper_scout
from src.literature.openalex import Candidate

logger = logging.getLogger(__name__)

EXIT_NO_NEW_CANDIDATES = 3

# 提示済みキーを埋め込むマーカー
_MARKER_LABEL = "paper-scout-presented:"
_MARKER_PATTERN = re.compile(r"<!--\s*paper-scout-presented:(.*?)-->", re.DOTALL)

# キーを URL エンコードする際に残す文字（`>` や空白はエンコードされ、マーカーを壊さない）
_KEY_SAFE_CHARS = ":/._;()"


def candidate_report_key(candidate: Candidate) -> str | None:
    """候補の提示済み判定キーを返す（正規化 DOI 優先・無ければ OpenAlex ID）。

    DOI の無い候補として提示した文献に後から OpenAlex 上で DOI が付くと、キーが
    ``openalex:`` から ``doi:`` に変わり、再び提示されうる（頻度が低く、再提示されても
    害が小さいため許容する）。

    Args:
        candidate: 文献候補。
    Returns:
        キー。DOI も OpenAlex ID も無ければ None。
    """
    if candidate.doi:
        return f"doi:{candidate.doi}"
    short_id = paper_scout.short_openalex_id(candidate.openalex_id)
    return f"openalex:{short_id}" if short_id else None


def format_marker(keys: Iterable[str]) -> str:
    """提示済みキーを埋め込んだ不可視マーカーを作る。

    Args:
        keys: 提示したキー。
    Returns:
        HTML コメント形式のマーカー。
    """
    encoded = " ".join(quote(key, safe=_KEY_SAFE_CHARS) for key in keys)
    return f"<!-- {_MARKER_LABEL} {encoded} -->"


def extract_presented_keys(comment_bodies: Iterable[str]) -> set[str]:
    """過去のコメント本文から、マーカーに記録された提示済みキーを集める。

    Args:
        comment_bodies: コメント本文の並び。
    Returns:
        提示済みキーの集合。
    """
    keys: set[str] = set()
    for body in comment_bodies:
        for match in _MARKER_PATTERN.finditer(body or ""):
            keys.update(unquote(token) for token in match.group(1).split())
    return keys


def load_comment_bodies(comments_json_path: Path) -> list[str]:
    """`gh api .../comments --paginate` の出力からコメント本文を取り出す。

    `--paginate` はページごとの JSON 配列を連結して出力するため（``[...][...]``）、
    先頭から順に配列を読み進める。

    コメントが0件の Issue でも `gh api` は ``[]`` を出力する。空ファイル（空白だけのものを
    含む）は `gh api` の失敗（認証切れ等）でリダイレクト先だけが作られた状態とみなし、
    「コメント0件」とは扱わない（提示済みの候補を除外できず、全件を再掲してしまうため）。

    Args:
        comments_json_path: 出力を保存したファイル。
    Returns:
        コメント本文のリスト。
    Raises:
        ValueError: ファイルが空の場合、または JSON 配列として解釈できない場合。
    """
    text = comments_json_path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError(
            "コメント一覧のファイルが空です（gh api の失敗が疑われます）: "
            f"{comments_json_path.name}"
        )
    decoder = json.JSONDecoder()
    bodies: list[str] = []
    position = 0
    while True:
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            break
        page, position = decoder.raw_decode(text, position)
        if not isinstance(page, list):
            raise ValueError(f"コメント一覧が JSON 配列ではありません: {comments_json_path.name}")
        bodies.extend(
            str(comment.get("body") or "") for comment in page if isinstance(comment, dict)
        )
    return bodies


def select_new_candidates(
    candidates: list[Candidate], presented_keys: set[str], top: int
) -> tuple[list[Candidate], int, int]:
    """提示済みの候補を除き、上位から指定件数を選ぶ。

    判定キーを作れない候補（DOI も OpenAlex ID も無いもの）は、提示済みかどうかを
    記録できないため掲載しない（提示済みの件数にも数えない）。

    Args:
        candidates: スコア降順の候補。
        presented_keys: 提示済みキー。
        top: 選ぶ件数の上限（1 以上）。
    Returns:
        (選んだ候補, 提示済みを除いた新規候補の総数, 提示済みとして除外した件数)。
    """
    new_candidates = []
    presented_count = 0
    for candidate in candidates:
        key = candidate_report_key(candidate)
        if key is None:
            continue
        if key in presented_keys:
            presented_count += 1
            continue
        new_candidates.append(candidate)
    return new_candidates[:top], len(new_candidates), presented_count


def format_report_comment(
    selected: list[Candidate],
    total_new: int,
    excluded_count: int,
    min_score: float,
    run_date: dt.date,
    skipped: list[str],
) -> str:
    """Issue に追記するコメント本文（Markdown）を作る。

    Args:
        selected: 表に載せる候補。
        total_new: 新規候補の総数（提示済みを除いた件数）。
        excluded_count: 提示済みとして除外した件数。
        min_score: 足切りに使ったスコア。
        run_date: 実行日。
        skipped: 解決できなかった起点の説明。
    Returns:
        コメント本文。
    """
    lines = [
        f"## 文献候補 {run_date:%Y-%m}（{run_date:%Y-%m-%d} 実行）",
        "",
        f"- 新規候補 {total_new} 件のうち上位 {len(selected)} 件を掲載"
        f"（スコア {min_score:g} 以上・前回までに提示済みの {excluded_count} 件を除外）",
        "- スコアは RQ キーワードの機械的な一致度であり、関連性の最終判断ではない。"
        "採否・精読・登録は研究者が `/add-paper` で行う",
        "",
        paper_scout.format_table(selected, len(selected)),
    ]
    if skipped:
        lines.extend(["", "<details><summary>解決できなかった起点</summary>", ""])
        lines.extend(f"- {line}" for line in skipped)
        lines.extend(["", "</details>"])
    keys = [key for key in (candidate_report_key(cand) for cand in selected) if key]
    lines.extend(["", format_marker(keys)])
    return "\n".join(lines) + "\n"


def positive_int(value: str) -> int:
    """1 以上の整数として引数を解釈する（argparse の type 用）。

    Args:
        value: 引数の文字列。
    Returns:
        解釈した整数。
    Raises:
        argparse.ArgumentTypeError: 整数でない、または 1 未満の場合。
    """
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"整数を指定してください: {value}") from exc
    if number < 1:
        raise argparse.ArgumentTypeError(f"1 以上の整数を指定してください: {value}")
    return number


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """コマンドライン引数を解釈する。"""
    parser = argparse.ArgumentParser(description="文献探索の月次報告コメントを生成する")
    parser.add_argument(
        "--comments-json",
        required=True,
        help="報告 Issue の既存コメント（gh api .../comments --paginate の出力）",
    )
    parser.add_argument("--output", required=True, help="コメント本文（Markdown）の出力先")
    parser.add_argument(
        "--csv",
        default="docs/04_archive/01_metadata/papers_database.csv",
        help="papers_database.csv の相対/絶対パス",
    )
    parser.add_argument("--s", default=None, help="起点 S 番号のカンマ区切り（省略時は全件）")
    parser.add_argument("--top", type=positive_int, default=15, help="コメントに載せる件数の上限")
    parser.add_argument(
        "--min-score", type=float, default=30.0, help="このスコア未満の候補を除外する"
    )
    parser.add_argument(
        "--max-forward", type=positive_int, default=400, help="1起点あたりの前方引用取得上限"
    )
    parser.add_argument("--timeout", type=positive_int, default=20, help="タイムアウト秒数")
    parser.add_argument(
        "--mailto", default=None, help="polite pool 用メールアドレス（API キー未設定時のみ）"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。終了コードはモジュールの説明を参照。"""
    openalex.force_utf8_output()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _parse_args(argv)
    try:
        comment_bodies = load_comment_bodies(resolve_existing_path(Path(args.comments_json)))
    except ValueError as exc:
        # 提示済みの候補を判定できないまま進むと全件を再掲しうるため、探索せずに終える
        print(f"既存コメントを読めませんでした: {exc}", file=sys.stderr)
        return 1
    presented_keys = extract_presented_keys(comment_bodies)
    candidates, skipped = paper_scout.scout(
        csv_path=resolve_existing_path(Path(args.csv)),
        s_numbers=args.s.split(",") if args.s else None,
        mailto=args.mailto,
        timeout=args.timeout,
        max_forward=args.max_forward,
    )
    if not candidates:
        # 起点の引用関係から候補が1件も得られないのは、起点の解決や OpenAlex への取得が
        # 失敗した場合に限られるため、「新規候補なし」ではなく失敗として扱う
        print("探索に失敗しました（候補を1件も取得できませんでした）。", file=sys.stderr)
        for line in skipped:
            print(f"  - {line}", file=sys.stderr)
        return 1

    filtered = openalex.filter_by_min_score(candidates, args.min_score)
    selected, total_new, excluded_count = select_new_candidates(filtered, presented_keys, args.top)
    print(
        f"候補 {len(filtered)} 件（スコア {args.min_score:g} 以上）／"
        f"提示済み {excluded_count} 件を除外／新規 {total_new} 件"
    )
    if not selected:
        print("新規候補が無いため、コメント本文は書き出しません。")
        return EXIT_NO_NEW_CANDIDATES

    output_path = prepare_output_path(Path(args.output))
    output_path.write_text(
        format_report_comment(
            selected, total_new, excluded_count, args.min_score, dt.date.today(), skipped
        ),
        encoding="utf-8",
    )
    print(f"コメント本文を書き出しました（{len(selected)} 件掲載）: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
