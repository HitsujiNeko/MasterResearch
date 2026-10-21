"""OpenAlex アクセスと文献スコアリングの共有ツールキット。

引用スノーボーリング（``paper_scout``）と新着文献ウォッチ（``paper_watch``）の
両方が用いる、OpenAlex への HTTP アクセス・書誌メタデータの解釈・RQ キーワードによる
スコアリング・``papers_database.csv`` との突合・出力整形の各処理を集約する。

キーワード語彙（``KEYWORD_WEIGHTS``）はここを単一の正本とし、両スクリプトが参照する。

OpenAlex アクセス方針:
- 認証は任意。環境変数 ``OPENALEX_API_KEY`` が設定されていればクエリに付与し、
  無料枠が10倍（1,000→10,000 list+filter/日）になる。未設定でも本用途の想定利用量は
  未認証の無料枠内に収まる。
- API キーはログ・出力に一切出さない（``_redact`` で伏字化する）。
- HTTP 429（無料枠超過）は探索を停止せず、当該リクエストをスキップして続行する。
- 複数ページの取得は cursor ではなく ``page=N`` の basic paging で行う（``fetch_paged``）。
  OpenAlex は API キーなしの cursor ページングを2ページ目以降で 401 として拒否するため。
"""

from __future__ import annotations

import csv
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src.common.http_fetch import fetch_json_with_retry

logger = logging.getLogger(__name__)

OPENALEX_BASE_URL = "https://api.openalex.org/works"

# OpenAlex から取得するフィールド（ペイロード削減のため select で絞る）
SELECT_FIELDS = (
    "id,doi,title,display_name,publication_year,primary_location,abstract_inverted_index"
)

# 1ページの取得件数（OpenAlex の per-page 上限）
PER_PAGE = 200

# basic paging（page=N）で取得できる先頭件数の上限（OpenAlex の仕様）
BASIC_PAGING_LIMIT = 10_000

# タイトルへのマッチはアブストラクトより重視するための倍率
_TITLE_WEIGHT = 2.0

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
    # 記号のみを空白へ。``\w`` は Unicode 対応（str の re は既定で Unicode 認識）のため、
    # 非 ASCII の文字・数字（アクセント付き・非ラテン文字など）は保持し、除去による
    # タイトルの欠落・別語への衝突を防ぐ。
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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


def extract_venue(work: dict[str, Any]) -> str | None:
    """OpenAlex work から掲載誌名を取り出す。"""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    return source.get("display_name")


def work_title(work: dict[str, Any]) -> str:
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


def candidate_key(work: dict[str, Any]) -> str | None:
    """候補の重複判定キー（正規化 DOI 優先・無ければ正規化タイトル）。"""
    doi = normalize_doi(work.get("doi"))
    if doi:
        return f"doi:{doi}"
    title = normalize_title(work_title(work))
    return f"title:{title}" if title else None


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
        return f"&api_key={quote(api_key, safe='')}"
    if mailto:
        return f"&mailto={quote(mailto, safe='')}"
    return ""


def build_url(query: str, mailto: str | None, select: str = SELECT_FIELDS) -> str:
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


def safe_fetch(url: str, timeout: int) -> dict[str, Any] | None:
    """_fetch_json をラップし、失敗時は None を返してスキップ可能にする。"""
    try:
        return _fetch_json(url, timeout)
    except (RuntimeError, ValueError) as exc:
        logger.warning("取得をスキップします（%s）: %s", exc, _redact(url))
        return None


def fetch_paged(
    query: str,
    mailto: str | None,
    timeout: int,
    max_results: int,
    sort: str,
    per_page: int = PER_PAGE,
) -> tuple[list[dict[str, Any]], bool]:
    """``page=1,2,...`` の basic paging で work を上限件数まで取得する。

    OpenAlex は API キーなしの cursor ページングを2ページ目以降で 401 として拒否するため、
    キーの有無によらず動く basic paging を用いる。basic paging は先頭
    ``BASIC_PAGING_LIMIT`` 件までしか取得できないため、そこで打ち切る。

    次のいずれかで打ち切る: 上限件数に達した／件数が ``per_page`` 未満のページ（最終ページ）／
    basic paging の上限に達した／リクエストが失敗した（取得済みの分は返す）。
    上限件数または basic paging の上限で続きを切り捨てたときは WARNING を出す。切り捨ての
    有無は最初のページの ``meta.count``（条件に合う総件数）で判定する。

    basic paging はページごとに独立した問い合わせになるため、並び順が一意に定まらないと
    ページの境目で順序が入れ替わり、重複と取りこぼしが起きる（並び順を指定しない場合に
    実測で確認）。そのため ``sort`` は必須とし、最後のキーには ``ids.openalex`` のような
    一意なキーを置く。

    Args:
        query: ``filter=...`` 等のクエリ断片（``per-page``・``page`` は付けない）。
        mailto: polite pool 用メールアドレス（API キー未設定時のみ使用）。
        timeout: タイムアウト秒数。
        max_results: 取得上限件数。
        sort: OpenAlex の ``sort`` パラメータ（例: ``cited_by_count:desc,ids.openalex``）。
            上限件数で打ち切る場合は、この並び順の先頭から取得する。
        per_page: 1ページの件数（OpenAlex の上限は 200）。
    Returns:
        (取得した work のリスト（最大 max_results 件）, 1回でも取得に成功したか)。
    """
    collected: list[dict[str, Any]] = []
    any_success = False
    total_count: int | None = None
    last_page_full = False
    max_page = BASIC_PAGING_LIMIT // per_page
    page = 1
    while len(collected) < max_results and page <= max_page:
        url = build_url(f"{query}&sort={sort}&per-page={per_page}&page={page}", mailto)
        result = safe_fetch(url, timeout)
        if result is None:
            break
        if not any_success:
            total_count = _total_count(result)
        any_success = True
        page_results = result.get("results") or []
        collected.extend(page_results)
        last_page_full = len(page_results) >= per_page
        if not last_page_full:
            break
        page += 1
    if _is_truncated_by_max_results(len(collected), max_results, total_count, last_page_full):
        logger.warning(
            "取得上限 %d 件に達したため打ち切りました（総件数: %s。並び順 %s の先頭から"
            "取得し、残りは取得していません）: %s",
            max_results,
            _format_count(total_count),
            sort,
            _redact(query),
        )
    reached_paging_limit = page > max_page and len(collected) < max_results
    # 総件数が分かれば、ちょうど上限件数で尽きた場合（最終ページが満杯）を除外できる
    if reached_paging_limit and (total_count is None or total_count > BASIC_PAGING_LIMIT):
        logger.warning(
            "basic paging の上限（先頭 %d 件）に達したため打ち切ります（総件数: %s）: %s",
            BASIC_PAGING_LIMIT,
            _format_count(total_count),
            _redact(query),
        )
    return collected[:max_results], any_success


def _total_count(result: dict[str, Any]) -> int | None:
    """OpenAlex の一覧応答から条件に合う総件数（``meta.count``）を取り出す。

    Args:
        result: OpenAlex の一覧応答。
    Returns:
        総件数。``meta.count`` が無い・整数でない場合は None。
    """
    meta = result.get("meta")
    if not isinstance(meta, dict):
        return None
    count = meta.get("count")
    # bool は int のサブクラスのため明示的に除外する
    if isinstance(count, int) and not isinstance(count, bool):
        return count
    return None


def _is_truncated_by_max_results(
    collected_count: int, max_results: int, total_count: int | None, last_page_full: bool
) -> bool:
    """取得上限で止めたとき、まだ続きがあった（切り捨てた）かを判定する。

    総件数が分かる場合はそれと上限を比べる。分からない場合は、上限を超えて取得していた
    か、最後のページが満杯だった（続きがありうる）ときに切り捨てとみなし、知らせる側に倒す。

    Args:
        collected_count: 取得済みの件数（上限で切り詰める前）。
        max_results: 取得上限件数。
        total_count: 条件に合う総件数（``meta.count``）。不明なら None。
        last_page_full: 最後に取得したページが ``per_page`` 件で満杯だったか。
    Returns:
        切り捨てが起きた（起きた可能性がある）場合は True。
    """
    # 上限に達していなければ、最終ページ・失敗・basic paging 上限など別の理由で止まっている
    if collected_count < max_results or max_results <= 0:
        return False
    if total_count is not None:
        return total_count > max_results
    return collected_count > max_results or last_page_full


def _format_count(count: int | None) -> str:
    """ログ用に件数を整形する（不明な場合は「不明」）。"""
    return "不明" if count is None else f"{count:,} 件"


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


# CSV 数式インジェクションの起点となりうる先頭文字（Excel 等で数式として解釈される）
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")


def sanitize_csv_cell(value: object) -> str:
    """CSV セルを数式インジェクションから保護する。

    OpenAlex 由来の外部文字列（タイトル・掲載誌・DOI 等）が ``=``/``+``/``-``/``@`` で
    始まる場合、表計算ソフトが数式として実行しないよう先頭に ``'`` を付ける。
    それ以外の値はそのまま返す。

    Args:
        value: セルの値（None・数値も許容する）。
    Returns:
        無害化済みの文字列。
    """
    text = "" if value is None else str(value)
    if text and text[0] in _CSV_FORMULA_PREFIXES:
        return "'" + text
    return text


def write_candidates_csv(candidates: list[Candidate], output_path: Path) -> None:
    """全候補を CSV に書き出す。"""
    # utf-8-sig（BOM 付き）で書き出し、Windows 版 Excel での日本語文字化けを防ぐ
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["スコア", "タイトル", "年", "掲載誌", "DOI", "経由", "方向", "マッチKW"])
        for cand in candidates:
            writer.writerow(
                [
                    f"{cand.score:.1f}",
                    # 外部由来の文字列は数式インジェクションを無害化する
                    sanitize_csv_cell(cand.title),
                    cand.year or "",
                    sanitize_csv_cell(cand.venue or ""),
                    sanitize_csv_cell(cand.doi or ""),
                    ";".join(sorted(cand.via_papers)),
                    ";".join(sorted(cand.directions)),
                    ";".join(sorted(cand.matched_keywords)),
                ]
            )


def force_utf8_output() -> None:
    """標準出力・標準エラーを UTF-8 に切り替える（Windows の cp932 文字化け対策）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
