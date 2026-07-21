"""引用スノーボーリングによる文献候補探索スクリプト。

`papers_database.csv` の登録済み文献（起点）の DOI/タイトルを OpenAlex で解決し、
前方引用（cited_by）・後方引用（references）をたどって、RQ1-3 キーワードで
スコアリングした未登録の文献候補を提示する。

探索と提示までを担い、候補の採否判断・精読・登録（/add-paper）は研究者が行う。

OpenAlex アクセス方針:
- 認証は任意。環境変数 ``OPENALEX_API_KEY`` が設定されていればクエリに付与し、
  無料枠が10倍（1,000→10,000 list+filter/日）になる。未設定でも本用途の想定利用量は
  未認証の無料枠内に収まる。
- API キーはログ・出力に一切出さない。
- HTTP 429（無料枠超過）は探索を停止せず、当該リクエストをスキップして続行する。

主な出力:
1. 標準出力: 上位候補のテーブル（スコア降順）
2. ``--output`` 指定時: 全候補の CSV
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.common.http_fetch import fetch_json_with_retry
from src.common.paths import prepare_output_path, resolve_existing_path

logger = logging.getLogger(__name__)

OPENALEX_BASE_URL = "https://api.openalex.org/works"

# OpenAlex から取得するフィールド（ペイロード削減のため select で絞る）
_SELECT_FIELDS = (
    "id,doi,title,display_name,publication_year,primary_location,abstract_inverted_index"
)

# 起点 work は後方引用（referenced_works）も取得する
_SELECT_START = _SELECT_FIELDS + ",referenced_works"

# 1リクエストで OR 連結する OpenAlex ID の最大数
_ID_BATCH_SIZE = 50

# タイトルへのマッチはアブストラクトより重視するための倍率
_TITLE_WEIGHT = 2.0

# タイトル検索フォールバックで起点として採用する最小の Jaccard 類似度
# （これ未満なら別論文とみなしスキップする）
_TITLE_MATCH_THRESHOLD = 0.5

# RQ1-3 に関連するキーワードと重み（小文字・単語境界で照合する）
# キーワード・重みは研究の関心に応じて調整してよい。
KEYWORD_WEIGHTS: dict[str, float] = {
    # LST・熱環境
    "land surface temperature": 3.0,
    "lst": 3.0,
    "surface urban heat island": 3.0,
    "suhi": 3.0,
    "urban heat island": 2.0,
    "thermal": 1.0,
    # 都市構造
    "urban structure": 2.0,
    "urban morphology": 2.0,
    "urban form": 2.0,
    "building density": 2.0,
    "impervious": 2.0,
    "land use": 1.0,
    "land cover": 1.0,
    "ndvi": 1.0,
    "ndbi": 1.0,
    "green cover": 1.0,
    # スケール（RQ2）
    "spatial resolution": 1.0,
    "aggregation": 1.0,
    "multi-scale": 2.0,
    "grid": 1.0,
    "neighborhood": 1.0,
    "scale": 1.0,
    # データ制約・地域（RQ3）
    "data-scarce": 3.0,
    "data-limited": 3.0,
    "developing": 1.0,
    "tropical": 1.0,
    "subtropical": 1.0,
    "southeast asia": 2.0,
    "vietnam": 3.0,
    "hanoi": 3.0,
}

# キーワード照合用に事前コンパイルした正規表現（単語境界つき）
_KEYWORD_PATTERNS: dict[str, re.Pattern[str]] = {
    keyword: re.compile(r"\b" + re.escape(keyword) + r"\b") for keyword in KEYWORD_WEIGHTS
}


@dataclass
class Candidate:
    """未登録の文献候補1件。"""

    openalex_id: str
    title: str
    year: int | None
    venue: str | None
    doi: str | None
    score: float = 0.0
    matched_keywords: set[str] = field(default_factory=set)
    via_papers: set[str] = field(default_factory=set)
    directions: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# DOI・タイトルの正規化
# ---------------------------------------------------------------------------
def normalize_doi(value: str | None) -> str | None:
    """DOI 文字列を正規化する。

    前後の空白・引用符・末尾句読点を除去し、``doi:`` および
    ``http(s)://doi.org/`` / ``http(s)://dx.doi.org/`` の各プレフィックスを
    除去してから小文字化する。``10.<prefix>/<suffix>`` 形式でなければ None を返す。

    Args:
        value: DOI もしくは DOI を含む URL。None も許容する。
    Returns:
        正規化済み DOI（例: ``10.3390/rs13214256``）。DOI とみなせない場合は None。
    """
    if not value:
        return None
    text = value.strip().strip("\"'").rstrip(".,;")
    text = re.sub(r"^doi:", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = text.strip().lower()
    if re.match(r"^10\.\d{4,9}/\S+$", text):
        return text
    return None


def normalize_title(value: str | None) -> str:
    """タイトルを照合用に正規化する（小文字化・記号除去・空白圧縮）。

    Args:
        value: タイトル文字列。None も許容する。
    Returns:
        正規化済みタイトル。None・空文字の場合は空文字。
    """
    if not value:
        return ""
    text = value.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
    tokens_left = set(normalize_title(left).split())
    tokens_right = set(normalize_title(right).split())
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
# OpenAlex レスポンスの解釈
# ---------------------------------------------------------------------------
def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """OpenAlex の abstract_inverted_index からアブストラクト本文を復元する。

    Args:
        inverted_index: 単語→出現位置リストの辞書。None・空も許容する。
    Returns:
        復元したアブストラクト。復元できない場合は空文字。
    """
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indices in inverted_index.items():
        for index in indices:
            positions.append((index, word))
    positions.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positions)


def _extract_venue(work: dict[str, Any]) -> str | None:
    """OpenAlex work から掲載誌名を取り出す。"""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    return source.get("display_name")


def _work_title(work: dict[str, Any]) -> str:
    """OpenAlex work からタイトルを取り出す（title 優先・display_name フォールバック）。"""
    return work.get("title") or work.get("display_name") or ""


def score_text(title: str, abstract: str) -> tuple[float, set[str]]:
    """タイトル・アブストラクトを RQ キーワードでスコアリングする。

    キーワードごとに ``重み × (タイトル出現数 × タイトル倍率 + アブスト出現数)`` を
    合算する。照合は小文字・単語境界で行う。

    Args:
        title: 論文タイトル。
        abstract: 復元済みアブストラクト（無い場合は空文字）。
    Returns:
        (合計スコア, マッチしたキーワード集合)。
    """
    title_lower = title.lower()
    abstract_lower = abstract.lower()
    total = 0.0
    matched: set[str] = set()
    for keyword, weight in KEYWORD_WEIGHTS.items():
        pattern = _KEYWORD_PATTERNS[keyword]
        title_hits = len(pattern.findall(title_lower))
        abstract_hits = len(pattern.findall(abstract_lower))
        if title_hits or abstract_hits:
            matched.add(keyword)
            total += weight * (title_hits * _TITLE_WEIGHT + abstract_hits)
    return total, matched


# ---------------------------------------------------------------------------
# papers_database.csv の読み込み
# ---------------------------------------------------------------------------
def load_registered(csv_path: Path) -> tuple[set[str], set[str]]:
    """papers_database.csv から既登録の DOI・タイトルの正規化集合を作る。

    Args:
        csv_path: papers_database.csv のパス。
    Returns:
        (正規化 DOI 集合, 正規化タイトル集合)。
    """
    dois: set[str] = set()
    titles: set[str] = set()
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            doi = normalize_doi(row.get("DOI_URL"))
            if doi:
                dois.add(doi)
            title = normalize_title(row.get("タイトル"))
            if title:
                titles.add(title)
    return dois, titles


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
            doi = normalize_doi(row.get("DOI_URL"))
            papers.append((paper_id, title, doi))
    return papers


# ---------------------------------------------------------------------------
# OpenAlex アクセス
# ---------------------------------------------------------------------------
def _auth_params(mailto: str | None) -> str:
    """認証・polite pool 用のクエリ断片を返す。

    環境変数 ``OPENALEX_API_KEY`` があれば ``api_key`` を優先付与する。
    無ければ mailto（polite pool）を付与する。いずれも無ければ空文字。

    Returns:
        ``&api_key=...`` または ``&mailto=...`` または空文字。
    """
    api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if api_key:
        return f"&api_key={api_key}"
    if mailto:
        return f"&mailto={mailto}"
    return ""


def _build_url(query: str, mailto: str | None, select: str = _SELECT_FIELDS) -> str:
    """OpenAlex works エンドポイントの URL を組み立てる（select・認証付き）。"""
    return f"{OPENALEX_BASE_URL}?{query}&select={select}{_auth_params(mailto)}"


def _fetch_json(url: str, timeout: int) -> dict[str, Any]:
    """OpenAlex から JSON を取得する（429 は即時失敗させ呼び出し側でスキップ）。

    Args:
        url: リクエスト URL。
        timeout: タイムアウト秒数。
    Returns:
        パース済み JSON。
    Raises:
        RuntimeError: リトライ上限超過・429 の場合（呼び出し側でスキップ判定）。
    """
    return fetch_json_with_retry(
        url,
        timeout=timeout,
        max_retry_count=2,
        retry_wait_seconds=3,
        rate_limit_max_retry_count=0,
    )


def _redact(url: str) -> str:
    """ログ出力用に URL から api_key を伏せる。"""
    return re.sub(r"api_key=[^&]*", "api_key=***", url)


def _safe_fetch(url: str, timeout: int) -> dict[str, Any] | None:
    """_fetch_json をラップし、失敗時は None を返してスキップ可能にする。"""
    try:
        return _fetch_json(url, timeout)
    except (RuntimeError, ValueError) as exc:
        logger.warning("取得をスキップします（%s）: %s", exc, _redact(url))
        return None


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
        url = _build_url(f"filter=doi:{doi}", mailto, select=_SELECT_START)
        result = _safe_fetch(url, timeout)
        works = (result or {}).get("results") or []
        if works:
            return works[0]
        logger.info("DOI で解決できませんでした（タイトル検索へ）: %s", doi)
    if not title:
        return None
    quoted = title.replace(" ", "%20")
    url = _build_url(f"search={quoted}&per-page=5", mailto, select=_SELECT_START)
    result = _safe_fetch(url, timeout)
    works = (result or {}).get("results") or []
    if not works:
        return None
    target = normalize_title(title)
    for work in works:
        if normalize_title(_work_title(work)) == target:
            return work
    # 完全一致が無い場合は、最も類似する候補を類似度で判定する。
    # 閾値未満は別論文とみなし採用しない（誤った起点による候補汚染を防ぐ）。
    best_work = max(works, key=lambda work: title_similarity(title, _work_title(work)))
    best_score = title_similarity(title, _work_title(best_work))
    if best_score >= _TITLE_MATCH_THRESHOLD:
        logger.info(
            "タイトル近似一致（類似度 %.2f）で起点採用: %r → %r",
            best_score,
            title,
            _work_title(best_work),
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
        url = _build_url(f"filter=openalex_id:{joined}&per-page={_ID_BATCH_SIZE}", mailto)
        result = _safe_fetch(url, timeout)
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
        url = _build_url(f"filter=cites:{short_id}&per-page=200&cursor={cursor}", mailto)
        result = _safe_fetch(url, timeout)
        if not result:
            break
        collected.extend(result.get("results") or [])
        cursor = (result.get("meta") or {}).get("next_cursor")
    return collected[:max_forward]


# ---------------------------------------------------------------------------
# 候補の集約
# ---------------------------------------------------------------------------
def _candidate_key(work: dict[str, Any]) -> str | None:
    """候補の重複判定キー（正規化 DOI 優先・無ければ正規化タイトル）。"""
    doi = normalize_doi(work.get("doi"))
    if doi:
        return f"doi:{doi}"
    title = normalize_title(_work_title(work))
    return f"title:{title}" if title else None


def add_candidate(
    candidates: dict[str, Candidate],
    work: dict[str, Any],
    via_paper: str,
    direction: str,
    registered_dois: set[str],
    registered_titles: set[str],
) -> None:
    """work を未登録なら候補集合に加える（既出なら経由情報を統合する）。"""
    doi = normalize_doi(work.get("doi"))
    title = _work_title(work)
    norm_title = normalize_title(title)
    if doi and doi in registered_dois:
        return
    if norm_title and norm_title in registered_titles:
        return
    key = _candidate_key(work)
    if key is None:
        return
    existing = candidates.get(key)
    if existing is None:
        abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
        score, matched = score_text(title, abstract)
        existing = Candidate(
            openalex_id=work.get("id") or "",
            title=title,
            year=work.get("publication_year"),
            venue=_extract_venue(work),
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
    registered_dois, registered_titles = load_registered(csv_path)
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
def filter_by_min_score(candidates: list[Candidate], min_score: float) -> list[Candidate]:
    """スコアが min_score 以上の候補のみを返す（順序は保つ）。

    Args:
        candidates: 候補リスト。
        min_score: 足切り閾値（この値未満を除外する）。
    Returns:
        閾値以上の候補リスト。
    """
    if min_score <= 0.0:
        return candidates
    return [cand for cand in candidates if cand.score >= min_score]


def write_candidates_csv(candidates: list[Candidate], output_path: Path) -> None:
    """全候補を CSV に書き出す。"""
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["スコア", "タイトル", "年", "掲載誌", "DOI", "経由", "方向", "マッチKW"])
        for cand in candidates:
            writer.writerow(
                [
                    f"{cand.score:.1f}",
                    cand.title,
                    cand.year or "",
                    cand.venue or "",
                    cand.doi or "",
                    ";".join(sorted(cand.via_papers)),
                    ";".join(sorted(cand.directions)),
                    ";".join(sorted(cand.matched_keywords)),
                ]
            )


def format_table(candidates: list[Candidate], top: int) -> str:
    """上位候補を Markdown テーブル文字列に整形する。"""
    lines = [
        "| # | スコア | タイトル | 年 | 掲載誌 | DOI | 経由 | 方向 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for index, cand in enumerate(candidates[:top], start=1):
        title = cand.title if len(cand.title) <= 80 else cand.title[:77] + "..."
        lines.append(
            f"| {index} | {cand.score:.1f} | {title} | {cand.year or ''} | "
            f"{cand.venue or ''} | {cand.doi or ''} | "
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
        help="全候補 CSV の出力先（省略時は標準出力のみ）",
    )
    return parser.parse_args(argv)


def _force_utf8_output() -> None:
    """標準出力・標準エラーを UTF-8 に切り替える（Windows の cp932 文字化け対策）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。"""
    _force_utf8_output()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _parse_args(argv)
    csv_path = resolve_existing_path(Path(args.csv))
    s_numbers = [s for s in args.s.split(",")] if args.s else None

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
    filtered = filter_by_min_score(candidates, args.min_score)
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
        write_candidates_csv(filtered, output_path)
        print(f"\n全候補を書き出しました: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
