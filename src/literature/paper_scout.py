"""引用スノーボーリングによる文献候補探索スクリプト。

`papers_database.csv` の登録済み文献（起点）の DOI/タイトルを OpenAlex で解決し、
前方引用（cited_by）・後方引用（references）をたどって、RQ1-3 キーワードで
スコアリングした未登録の文献候補を提示する。

探索と提示までを担い、候補の採否判断・精読・登録（/add-paper）は研究者が行う。

OpenAlex アクセス・スコアリング・突合・出力整形の共有処理は
[openalex](openalex.py) から再利用する（キーワード語彙 ``KEYWORD_WEIGHTS`` も同モジュールが正本）。

主な出力:
1. 標準出力: 上位候補のテーブル（スコア降順）
2. ``--output`` 指定時: 全候補の CSV
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src.common.paths import prepare_output_path, resolve_existing_path
from src.literature import openalex
from src.literature.openalex import Candidate

logger = logging.getLogger(__name__)

# 起点 work は後方引用（referenced_works）も取得する
_SELECT_START = openalex.SELECT_FIELDS + ",referenced_works"

# 1リクエストで OR 連結する OpenAlex ID の最大数
_ID_BATCH_SIZE = 50

# タイトル検索フォールバックで起点として採用する最小の Jaccard 類似度
# （これ未満なら別論文とみなしスキップする）
_TITLE_MATCH_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# 起点解決の補助
# ---------------------------------------------------------------------------
def title_similarity(left: str, right: str) -> float:
    """2つのタイトルのトークン集合 Jaccard 類似度を返す（0.0〜1.0）。

    正規化後の単語集合の重なり（|A∩B| / |A∪B|）で測る。誤った起点採用を
    防ぐための粗い一致判定に用いる。

    Args:
        left: タイトル1。
        right: タイトル2。
    Returns:
        Jaccard 類似度。どちらかが空なら 0.0。
    """
    tokens_left = set(openalex.normalize_title(left).split())
    tokens_right = set(openalex.normalize_title(right).split())
    if not tokens_left or not tokens_right:
        return 0.0
    intersection = tokens_left & tokens_right
    union = tokens_left | tokens_right
    return len(intersection) / len(union)


def short_openalex_id(openalex_id: str | None) -> str | None:
    """OpenAlex の ID(URL) から短縮 ID（例: ``W123``）を取り出す。

    Args:
        openalex_id: ``https://openalex.org/W123`` 形式の ID。
    Returns:
        短縮 ID。取り出せない場合は None。
    """
    if not openalex_id:
        return None
    return openalex_id.rstrip("/").rsplit("/", 1)[-1] or None


# ---------------------------------------------------------------------------
# papers_database.csv の読み込み（起点）
# ---------------------------------------------------------------------------
def read_starting_papers(
    csv_path: Path, s_numbers: list[str] | None
) -> list[tuple[str, str, str | None]]:
    """起点論文（ID・タイトル・DOI）を papers_database.csv から読み込む。

    Args:
        csv_path: papers_database.csv のパス。
        s_numbers: 対象とする S 番号（例: ``["S1", "S5"]``）。None なら全件。
    Returns:
        (S番号, タイトル, 正規化DOI or None) のリスト。
    """
    wanted = {s.strip().upper() for s in s_numbers} if s_numbers else None
    papers: list[tuple[str, str, str | None]] = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            paper_id = (row.get("ID") or "").strip()
            if not paper_id:
                continue
            if wanted is not None and paper_id.upper() not in wanted:
                continue
            title = (row.get("タイトル") or "").strip()
            doi = openalex.normalize_doi(row.get("DOI_URL"))
            papers.append((paper_id, title, doi))
    return papers


# ---------------------------------------------------------------------------
# 起点解決・引用取得
# ---------------------------------------------------------------------------
def resolve_start_work(
    title: str, doi: str | None, mailto: str | None, timeout: int
) -> dict[str, Any] | None:
    """起点論文を OpenAlex work に解決する。

    DOI があれば単一エンティティ取得、無ければタイトル検索の最上位候補を用いる。

    Args:
        title: 論文タイトル（DOI が無い場合の検索キー）。
        doi: 正規化済み DOI（無い場合は None）。
        mailto: polite pool 用メールアドレス。
        timeout: タイムアウト秒数。
    Returns:
        OpenAlex work。解決できない場合は None。
    """
    if doi:
        url = openalex.build_url(f"filter=doi:{doi}", mailto, select=_SELECT_START)
        result = openalex.safe_fetch(url, timeout)
        works = (result or {}).get("results") or []
        if works:
            return works[0]
        logger.info("DOI で解決できませんでした（タイトル検索へ）: %s", doi)
    if not title:
        return None
    quoted = quote(title)
    url = openalex.build_url(f"search={quoted}&per-page=5", mailto, select=_SELECT_START)
    result = openalex.safe_fetch(url, timeout)
    works = (result or {}).get("results") or []
    if not works:
        return None
    target = openalex.normalize_title(title)
    for work in works:
        if openalex.normalize_title(openalex.work_title(work)) == target:
            return work
    # 完全一致が無い場合は、最も類似する候補を類似度で判定する。
    # 閾値未満は別論文とみなし採用しない（誤った起点による候補汚染を防ぐ）。
    best_work = max(works, key=lambda work: title_similarity(title, openalex.work_title(work)))
    best_score = title_similarity(title, openalex.work_title(best_work))
    if best_score >= _TITLE_MATCH_THRESHOLD:
        logger.info(
            "タイトル近似一致（類似度 %.2f）で起点採用: %r → %r",
            best_score,
            title,
            openalex.work_title(best_work),
        )
        return best_work
    logger.warning(
        "タイトル一致が弱く（類似度 %.2f）起点を採用しません: %r",
        best_score,
        title,
    )
    return None


def fetch_backward(work: dict[str, Any], mailto: str | None, timeout: int) -> list[dict[str, Any]]:
    """後方引用（参考文献）の work メタデータを取得する。

    Args:
        work: 起点の OpenAlex work（``referenced_works`` を含む）。
        mailto: polite pool 用メールアドレス。
        timeout: タイムアウト秒数。
    Returns:
        参考文献 work のリスト（取得できたもののみ）。
    """
    referenced = work.get("referenced_works") or []
    short_ids = [short_openalex_id(ref) for ref in referenced]
    short_ids = [sid for sid in short_ids if sid]
    collected: list[dict[str, Any]] = []
    for start in range(0, len(short_ids), _ID_BATCH_SIZE):
        batch = short_ids[start : start + _ID_BATCH_SIZE]
        joined = "|".join(batch)
        url = openalex.build_url(f"filter=ids.openalex:{joined}&per-page={_ID_BATCH_SIZE}", mailto)
        result = openalex.safe_fetch(url, timeout)
        if result:
            collected.extend(result.get("results") or [])
    return collected


def fetch_forward(
    short_id: str, mailto: str | None, timeout: int, max_forward: int
) -> list[dict[str, Any]]:
    """前方引用（被引用）の work メタデータを cursor ページングで取得する。

    Args:
        short_id: 起点 work の短縮 ID（例: ``W123``）。
        mailto: polite pool 用メールアドレス。
        timeout: タイムアウト秒数。
        max_forward: 取得上限件数（暴走防止）。
    Returns:
        被引用 work のリスト（最大 max_forward 件）。
    """
    collected: list[dict[str, Any]] = []
    cursor = "*"
    while cursor and len(collected) < max_forward:
        url = openalex.build_url(f"filter=cites:{short_id}&per-page=200&cursor={cursor}", mailto)
        result = openalex.safe_fetch(url, timeout)
        if not result:
            break
        collected.extend(result.get("results") or [])
        cursor = (result.get("meta") or {}).get("next_cursor")
    return collected[:max_forward]


# ---------------------------------------------------------------------------
# 候補の集約
# ---------------------------------------------------------------------------
def add_candidate(
    candidates: dict[str, Candidate],
    work: dict[str, Any],
    via_paper: str,
    direction: str,
    registered_dois: set[str],
    registered_titles: set[str],
) -> None:
    """work を未登録なら候補集合に加える（既出なら経由情報を統合する）。"""
    doi = openalex.normalize_doi(work.get("doi"))
    title = openalex.work_title(work)
    norm_title = openalex.normalize_title(title)
    if doi and doi in registered_dois:
        return
    if norm_title and norm_title in registered_titles:
        return
    key = openalex.candidate_key(work)
    if key is None:
        return
    existing = candidates.get(key)
    if existing is None:
        abstract = openalex.reconstruct_abstract(work.get("abstract_inverted_index"))
        score, matched = openalex.score_text(title, abstract)
        existing = Candidate(
            openalex_id=work.get("id") or "",
            title=title,
            year=work.get("publication_year"),
            venue=openalex.extract_venue(work),
            doi=doi,
            score=score,
            matched_keywords=matched,
        )
        candidates[key] = existing
    existing.via_papers.add(via_paper)
    existing.directions.add(direction)


def scout(
    csv_path: Path,
    s_numbers: list[str] | None,
    mailto: str | None,
    timeout: int,
    max_forward: int,
) -> tuple[list[Candidate], list[str]]:
    """引用スノーボーリングを実行し、未登録候補と起点スキップ理由を返す。

    Args:
        csv_path: papers_database.csv のパス。
        s_numbers: 起点とする S 番号。None なら全件。
        mailto: polite pool 用メールアドレス。
        timeout: タイムアウト秒数。
        max_forward: 1起点あたりの前方引用取得上限。
    Returns:
        (スコア降順の候補リスト, 解決できなかった起点の説明リスト)。
    """
    registered_dois, registered_titles = openalex.load_registered(csv_path)
    starts = read_starting_papers(csv_path, s_numbers)
    candidates: dict[str, Candidate] = {}
    skipped: list[str] = []
    for paper_id, title, doi in starts:
        work = resolve_start_work(title, doi, mailto, timeout)
        if work is None:
            skipped.append(f"{paper_id}: 起点をOpenAlexで解決できませんでした")
            continue
        short_id = short_openalex_id(work.get("id"))
        logger.info("起点 %s を解決（%s）", paper_id, short_id)
        for ref_work in fetch_backward(work, mailto, timeout):
            add_candidate(
                candidates,
                ref_work,
                paper_id,
                "後方",
                registered_dois,
                registered_titles,
            )
        if short_id:
            for citing_work in fetch_forward(short_id, mailto, timeout, max_forward):
                add_candidate(
                    candidates,
                    citing_work,
                    paper_id,
                    "前方",
                    registered_dois,
                    registered_titles,
                )
    ranked = sorted(
        candidates.values(),
        key=lambda cand: (cand.score, cand.year or 0),
        reverse=True,
    )
    return ranked, skipped


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
def format_table(candidates: list[Candidate], top: int) -> str:
    """上位候補を Markdown テーブル文字列に整形する。"""
    lines = [
        "| # | スコア | タイトル | 年 | 掲載誌 | DOI | 経由 | 方向 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for index, cand in enumerate(candidates[:top], start=1):
        title = cand.title if len(cand.title) <= 80 else cand.title[:77] + "..."
        # セル内の | は表の区切りと衝突するためエスケープする
        title = title.replace("|", "\\|")
        venue = (cand.venue or "").replace("|", "\\|")
        lines.append(
            f"| {index} | {cand.score:.1f} | {title} | {cand.year or ''} | "
            f"{venue} | {cand.doi or ''} | "
            f"{';'.join(sorted(cand.via_papers))} | "
            f"{';'.join(sorted(cand.directions))} |"
        )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """コマンドライン引数を解釈する。"""
    parser = argparse.ArgumentParser(description="OpenAlex 引用スノーボーリングによる文献候補探索")
    parser.add_argument(
        "--csv",
        default="docs/04_archive/01_metadata/papers_database.csv",
        help="papers_database.csv の相対/絶対パス",
    )
    parser.add_argument(
        "--s",
        default=None,
        help="起点 S 番号のカンマ区切り（例: S1,S5）。省略時は全件",
    )
    parser.add_argument("--top", type=int, default=20, help="標準出力に表示する件数")
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="このスコア未満の候補を除外する（既定 0.0＝除外なし）",
    )
    parser.add_argument(
        "--max-forward",
        type=int,
        default=400,
        help="1起点あたりの前方引用取得上限",
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
        help="候補 CSV の出力先（--min-score 適用後の候補・省略時は標準出力のみ）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。"""
    openalex.force_utf8_output()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _parse_args(argv)
    csv_path = resolve_existing_path(Path(args.csv))
    s_numbers = args.s.split(",") if args.s else None

    candidates, skipped = scout(
        csv_path=csv_path,
        s_numbers=s_numbers,
        mailto=args.mailto,
        timeout=args.timeout,
        max_forward=args.max_forward,
    )

    if skipped:
        print("【解決できなかった起点】", file=sys.stderr)
        for line in skipped:
            print(f"  - {line}", file=sys.stderr)

    total = len(candidates)
    filtered = openalex.filter_by_min_score(candidates, args.min_score)
    if args.min_score > 0.0:
        print(
            f"未登録の候補: {len(filtered)} 件"
            f"（スコア {args.min_score:g} 以上・全 {total} 件中／上位 {args.top} 件表示）\n"
        )
    else:
        print(f"未登録の候補: {total} 件（スコア降順・上位 {args.top} 件）\n")
    print(format_table(filtered, args.top))

    if args.output:
        output_path = prepare_output_path(Path(args.output))
        openalex.write_candidates_csv(filtered, output_path)
        print(f"\n候補を書き出しました: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
