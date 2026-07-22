"""OpenAlex 新着文献ウォッチスクリプト。

研究テーマ（LST × 都市構造）に関連する**過去 N 日の新着論文**を OpenAlex で検索し、
`papers_database.csv` と突合して**未登録のみ**をスコア降順で提示する。
`/weekly-digest` スキルの「📚 新着文献候補」セクションの素材を生成する。

引用スノーボーリング（起点論文からの前方/後方引用）を担う ``paper_scout`` の姉妹スクリプトで、
OpenAlex アクセス・スコアリング・DOI/タイトル突合・整形の各処理を ``paper_scout`` から再利用する。
キーワード語彙（``KEYWORD_WEIGHTS``）も ``paper_scout`` を単一の正本として共有する。

OpenAlex アクセス方針:
- 認証は任意。環境変数 ``OPENALEX_API_KEY`` があればクエリに付与し無料枠が10倍になる。
  未設定でも本用途（週次・単一クエリ）の想定利用量は未認証の無料枠内に収まる。
- API キーはログ・出力に一切出さない。
- HTTP 失敗・429 は探索を停止せず、``fetched_ok=False`` を返して**セクションをスキップ**可能にする
  （ダイジェスト全体は止めない）。

主な出力:
1. 標準出力: 上位候補のテーブル（スコア降順）
2. ``--output`` 指定時: 全候補の CSV
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src.common.paths import prepare_output_path, resolve_existing_path
from src.literature import paper_scout
from src.literature.paper_scout import Candidate

logger = logging.getLogger(__name__)

# 新着検索の中核語（title_and_abstract.search で OR 連結する）。
# 検索は熱環境の中核概念に絞ってノイズを抑え、スコアリングは全キーワードで行う二段構え。
# 各語は共有語彙 KEYWORD_WEIGHTS に含まれることをモジュール読み込み時に保証する（ドリフト防止）。
CORE_SEARCH_TERMS: tuple[str, ...] = (
    "land surface temperature",
    "surface urban heat island",
    "urban heat island",
)

# 検索の既定対象期間（日数）
_DEFAULT_DAYS = 7

# 1回の実行で取得する新着 work の上限（暴走防止）
_DEFAULT_MAX_RESULTS = 400

_missing_terms = [term for term in CORE_SEARCH_TERMS if term not in paper_scout.KEYWORD_WEIGHTS]
if _missing_terms:
    raise RuntimeError(
        f"CORE_SEARCH_TERMS が KEYWORD_WEIGHTS に未定義です（語彙のドリフト）: {_missing_terms}"
    )


# ---------------------------------------------------------------------------
# 検索式・日付
# ---------------------------------------------------------------------------
def default_from_date(days: int, today: dt.date | None = None) -> str:
    """検索の開始日（``today`` の ``days`` 日前）を ISO 文字列で返す。

    Args:
        days: 遡る日数。
        today: 基準日。None なら当日（テスト用に注入可能）。
    Returns:
        ``YYYY-MM-DD`` 形式の開始日。
    """
    base = today or dt.date.today()
    return (base - dt.timedelta(days=days)).isoformat()


def build_search_filter(from_date: str) -> str:
    """OpenAlex works の ``filter`` 値（未エンコード）を組み立てる。

    ``from_publication_date`` で期間を絞り、``title_and_abstract.search`` で中核語を OR 検索する。

    Args:
        from_date: 検索開始日（``YYYY-MM-DD``）。
    Returns:
        ``from_publication_date:...,title_and_abstract.search:...`` 形式の filter 値。
    """
    search_value = " OR ".join(f'"{term}"' for term in CORE_SEARCH_TERMS)
    return f"from_publication_date:{from_date},title_and_abstract.search:{search_value}"


# ---------------------------------------------------------------------------
# OpenAlex アクセス
# ---------------------------------------------------------------------------
def fetch_recent(
    from_date: str, mailto: str | None, timeout: int, max_results: int
) -> tuple[list[dict[str, Any]], bool]:
    """新着 work を cursor ページングで取得する。

    Args:
        from_date: 検索開始日（``YYYY-MM-DD``）。
        mailto: polite pool 用メールアドレス（API キー未設定時のみ使用）。
        timeout: タイムアウト秒数。
        max_results: 取得上限件数。
    Returns:
        (取得した work のリスト, 1回でも取得に成功したか)。
        1ページ目から取得に失敗した場合は ``([], False)``（＝API 不通としてスキップ可能）。
    """
    collected: list[dict[str, Any]] = []
    any_success = False
    cursor: str | None = "*"
    encoded_filter = quote(build_search_filter(from_date), safe=":,")
    while cursor and len(collected) < max_results:
        query = f"filter={encoded_filter}&per-page=200&cursor={cursor}"
        url = paper_scout._build_url(query, mailto)
        result = paper_scout._safe_fetch(url, timeout)
        if result is None:
            break
        any_success = True
        page_results = result.get("results") or []
        # 結果0件のページで打ち切る（データ終端、および cursor が進まない場合の暴走防止）
        if not page_results:
            break
        collected.extend(page_results)
        cursor = (result.get("meta") or {}).get("next_cursor")
    return collected[:max_results], any_success


# ---------------------------------------------------------------------------
# 候補の集約
# ---------------------------------------------------------------------------
def _build_candidate(work: dict[str, Any]) -> Candidate:
    """OpenAlex work から候補（スコア・マッチキーワード付き）を構築する。"""
    doi = paper_scout.normalize_doi(work.get("doi"))
    title = paper_scout._work_title(work)
    abstract = paper_scout.reconstruct_abstract(work.get("abstract_inverted_index"))
    score, matched = paper_scout.score_text(title, abstract)
    return Candidate(
        openalex_id=work.get("id") or "",
        title=title,
        year=work.get("publication_year"),
        venue=paper_scout._extract_venue(work),
        doi=doi,
        score=score,
        matched_keywords=matched,
    )


def collect_candidates(
    works: list[dict[str, Any]],
    registered_dois: set[str],
    registered_titles: set[str],
) -> list[Candidate]:
    """未登録の work をスコア降順の候補リストに集約する（DOI/タイトルで重複排除）。

    Args:
        works: OpenAlex から取得した work のリスト。
        registered_dois: 既登録の正規化 DOI 集合。
        registered_titles: 既登録の正規化タイトル集合。
    Returns:
        スコア降順（同点は新しい年を優先）の未登録候補リスト。
    """
    candidates: dict[str, Candidate] = {}
    for work in works:
        doi = paper_scout.normalize_doi(work.get("doi"))
        norm_title = paper_scout.normalize_title(paper_scout._work_title(work))
        if doi and doi in registered_dois:
            continue
        if norm_title and norm_title in registered_titles:
            continue
        key = paper_scout._candidate_key(work)
        if key is None or key in candidates:
            continue
        candidates[key] = _build_candidate(work)
    return sorted(
        candidates.values(),
        key=lambda cand: (cand.score, cand.year or 0),
        reverse=True,
    )


def watch(
    csv_path: Path,
    days: int,
    mailto: str | None,
    timeout: int,
    max_results: int,
    today: dt.date | None = None,
) -> tuple[list[Candidate], str, bool]:
    """新着文献ウォッチを実行し、未登録候補・検索開始日・取得可否を返す。

    Args:
        csv_path: papers_database.csv のパス。
        days: 遡る日数。
        mailto: polite pool 用メールアドレス。
        timeout: タイムアウト秒数。
        max_results: 取得上限件数。
        today: 基準日（テスト用に注入可能）。None なら当日。
    Returns:
        (スコア降順の未登録候補, 検索開始日 ``YYYY-MM-DD``, 取得に成功したか)。
        取得失敗時は候補が空・``fetched_ok=False``（呼び出し側でセクションをスキップする）。
    """
    from_date = default_from_date(days, today)
    registered_dois, registered_titles = paper_scout.load_registered(csv_path)
    works, fetched_ok = fetch_recent(from_date, mailto, timeout, max_results)
    if not fetched_ok:
        return [], from_date, False
    candidates = collect_candidates(works, registered_dois, registered_titles)
    return candidates, from_date, True


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
def format_watch_table(candidates: list[Candidate], top: int) -> str:
    """上位候補を Markdown テーブル文字列に整形する（新着ウォッチ用）。"""
    lines = [
        "| # | スコア | タイトル | 年 | 掲載誌 | DOI | マッチKW |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, cand in enumerate(candidates[:top], start=1):
        title = cand.title if len(cand.title) <= 80 else cand.title[:77] + "..."
        # セル内の | は表の区切りと衝突するためエスケープする
        title = title.replace("|", "\\|")
        venue = (cand.venue or "").replace("|", "\\|")
        matched = ";".join(sorted(cand.matched_keywords))
        lines.append(
            f"| {index} | {cand.score:.1f} | {title} | {cand.year or ''} | "
            f"{venue} | {cand.doi or ''} | {matched} |"
        )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """コマンドライン引数を解釈する。"""
    parser = argparse.ArgumentParser(
        description="OpenAlex 新着文献ウォッチ（研究テーマ関連の新着論文検索）"
    )
    parser.add_argument(
        "--csv",
        default="docs/04_archive/01_metadata/papers_database.csv",
        help="papers_database.csv の相対/絶対パス",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=_DEFAULT_DAYS,
        help=f"遡る日数（既定 {_DEFAULT_DAYS}）",
    )
    parser.add_argument("--top", type=int, default=20, help="標準出力に表示する件数")
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="このスコア未満の候補を除外する（既定 0.0＝除外なし）",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=_DEFAULT_MAX_RESULTS,
        help=f"取得する新着 work の上限（既定 {_DEFAULT_MAX_RESULTS}）",
    )
    parser.add_argument("--timeout", type=int, default=20, help="タイムアウト秒数")
    parser.add_argument(
        "--mailto",
        default=None,
        help="polite pool 用メールアドレス（API キー未設定時のみ使用）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="全候補 CSV の出力先（省略時は標準出力のみ）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。"""
    paper_scout._force_utf8_output()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _parse_args(argv)
    csv_path = resolve_existing_path(Path(args.csv))

    candidates, from_date, fetched_ok = watch(
        csv_path=csv_path,
        days=args.days,
        mailto=args.mailto,
        timeout=args.timeout,
        max_results=args.max_results,
    )

    if not fetched_ok:
        print(
            f"新着文献検索をスキップしました（OpenAlex への接続に失敗）。開始日: {from_date}",
            file=sys.stderr,
        )
        return 0

    total = len(candidates)
    filtered = paper_scout.filter_by_min_score(candidates, args.min_score)
    if args.min_score > 0.0:
        print(
            f"新着の未登録候補: {len(filtered)} 件"
            f"（{from_date} 以降・スコア {args.min_score:g} 以上・"
            f"全 {total} 件中／上位 {args.top} 件表示）\n"
        )
    else:
        print(f"新着の未登録候補: {total} 件（{from_date} 以降・スコア降順・上位 {args.top} 件）\n")
    if filtered:
        print(format_watch_table(filtered, args.top))
    else:
        print("該当なし（新着の未登録候補は見つかりませんでした）")

    if args.output:
        output_path = prepare_output_path(Path(args.output))
        paper_scout.write_candidates_csv(filtered, output_path)
        print(f"\n候補を書き出しました: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
