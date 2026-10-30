"""LAADS DAAC のファイル一覧の取得・解釈・検証。

一覧が返すファイル名と `downloadsLink` は外部由来の値のため、キャッシュのパス・
トークンの送信先として使ってよいかをここで検証する。
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Any

from src.common.http_fetch import fetch_bytes_with_retry, is_allowed_https_url
from src.preprocessing.black_marble.product import (
    ANNUAL_DAY_OF_YEAR,
    LAADS_ARCHIVE_SET,
    PRODUCT_NAME,
)
from src.preprocessing.black_marble.tile_grid import TileIndex

logger = logging.getLogger(__name__)

LAADS_DETAILS_API_BASE = "https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/details/allData"

# Earthdata トークンを付けて叩いてよいホスト。一覧が返す URL は外部由来のため、
# トークンの送信先をここに固定する。一覧 API と同じホストから導き、二重管理を避ける。
ALLOWED_DOWNLOAD_HOSTS = frozenset({urllib.parse.urlparse(LAADS_DETAILS_API_BASE).hostname or ""})
# リダイレクトを追ってよいホスト。未認証・未同意時の LAADS は Earthdata の OAuth へ
# 転送するため、その正常系を通すには認証ホストも含める必要がある。
EARTHDATA_OAUTH_HOST = "urs.earthdata.nasa.gov"
ALLOWED_REDIRECT_HOSTS = ALLOWED_DOWNLOAD_HOSTS | {EARTHDATA_OAUTH_HOST}

# LAADS の一覧取得は軽いが、タイル本体は 100MB 超のため別のタイムアウトを与える
LISTING_TIMEOUT_SECONDS = 120

# ファイル名として受け付けない文字。一覧の値をそのままキャッシュのパスに使うため、
# ディレクトリ区切り・ドライブ指定を含む名前は保存先の外へ書き出しうる。
# 実行 OS に依らず弾けるよう、`/` と `\` の両方を区切りとみなす。
UNSAFE_FILE_NAME_CHARACTERS = ("/", "\\", ":")


@dataclass(frozen=True)
class TileFile:
    """LAADS の一覧が返すファイル情報。

    Attributes:
        name: ファイル名。
        download_url: 実際に配信される URL（一覧の `downloadsLink`）。
        size_bytes: ファイルサイズ。一覧に無ければ None。
    """

    name: str
    download_url: str
    size_bytes: int | None = None


def build_listing_url(year: int) -> str:
    """対象年のファイル一覧を取得する URL を組み立てる。

    Args:
        year: 取得対象年。

    Returns:
        LAADS DAAC の details API の URL。
    """
    return (
        f"{LAADS_DETAILS_API_BASE}/{LAADS_ARCHIVE_SET}/{PRODUCT_NAME}/{year}/"
        f"{ANNUAL_DAY_OF_YEAR}?fields=all&formats=json"
    )


def fetch_tile_listing(year: int, headers: dict[str, str]) -> dict[str, Any]:
    """対象年のファイル一覧を取得する。

    未認証・トークン期限切れのとき、LAADS は 401 ではなく **Earthdata のログイン
    ページへ 302 リダイレクトして HTML を返す**。そのまま JSON として解釈すると
    `Expecting value: line 1 column 1` という原因の分からない例外になるため、
    JSON でなかった場合は認証を疑う旨を添えて投げ直す。

    Args:
        year: 取得対象年。
        headers: 認証ヘッダー。

    Returns:
        一覧 API のレスポンス（JSON をパースした辞書）。

    Raises:
        RuntimeError: レスポンスが JSON として解釈できない場合。
    """
    response_body = fetch_bytes_with_retry(
        build_listing_url(year),
        timeout=LISTING_TIMEOUT_SECONDS,
        headers=headers,
        allowed_redirect_hosts=ALLOWED_REDIRECT_HOSTS,
    )
    try:
        return json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        preview = response_body[:200].decode("utf-8", errors="replace")
        raise RuntimeError(
            "LAADS の一覧が JSON で返りませんでした。"
            "Earthdata のトークンが無効・期限切れの可能性があります"
            "（未認証だとログインページへリダイレクトされ HTML が返ります）。"
            f"応答の先頭: {preview!r}"
        ) from exc


def is_safe_tile_file_name(name: str) -> bool:
    """一覧が返したファイル名を、そのままキャッシュのパスに使ってよいか判定する。

    一覧の `name` は**唯一そのままファイルシステムのパスになる外部由来の値**で、
    ディレクトリ区切りや親ディレクトリ参照を含んでいると、キャッシュ先の外へ
    100MB 超を書き出しうる。`run_inspection` の glob からも外れるため、
    取得済みのはずのファイルが見つからない状態にもなる。

    Args:
        name: 一覧が返したファイル名。

    Returns:
        安全に使えるファイル名なら True。
    """
    if name in ("", ".", ".."):
        return False
    return not any(character in name for character in UNSAFE_FILE_NAME_CHARACTERS)


def is_safe_download_url(url: str) -> bool:
    """一覧が返した URL を、認証ヘッダーを付けて叩いてよいか判定する。

    ファイル名と同じく、一覧の `downloadsLink` も外部由来の値である。この URL は
    Earthdata の Bearer トークンを添えて取得するため、宛先を許可ホストへ限る。
    `find_license_gate` の経路は `fetch_bytes_with_retry` のスキーム検証を通らない
    ため、`file://` などもここで弾く。

    **本関数が見るのは初回 URL だけである**。`urllib` はリダイレクト先へも
    `Authorization` を引き継ぐため、初回 URL の検証だけではリダイレクト経由の
    流出を防げない。取得時には `allowed_redirect_hosts` を併せて渡すこと
    （`ALLOWED_REDIRECT_HOSTS` / `RestrictedRedirectHandler` 参照）。

    Args:
        url: 一覧が返した URL。

    Returns:
        スキームが https で、かつ許可したホストであれば True。
    """
    return is_allowed_https_url(url, ALLOWED_DOWNLOAD_HOSTS)


def parse_listing_size(raw_size: Any, file_name: str) -> int | None:
    """一覧が返すファイルサイズを整数へ変換する。

    サイズは `download_tile` の「転送が途中で切れていないか」の検証に使う唯一の
    手掛かりで、None にすると**検証が例外にも警告にもならず飛ばされる**。配布側の
    属性は実際に想定と違っていた前例（`add_offset` ではなく `offset`）があるため、
    型を int に決め打ちせず、文字列・浮動小数点でも受け取る。解釈できない場合は
    「検証が無効になる」ことが分かるよう警告を残す。

    Args:
        raw_size: 一覧の `size` の生の値。
        file_name: 警告に添えるファイル名。

    Returns:
        バイト数。解釈できない場合は None。
    """
    # bool は int の派生だがサイズとしては無意味なので先に弾く
    if raw_size is not None and not isinstance(raw_size, bool):
        text = str(raw_size).strip()
        try:
            return int(text)
        except ValueError:
            try:
                # "1.19818130e8" のような表記に備える。整数化は切り捨てで足りる。
                # NaN は ValueError、inf は OverflowError になるため両方を捕まえる
                return int(float(text))
            except (ValueError, OverflowError):
                pass
    if raw_size is None:
        return None
    logger.warning(
        "一覧の %s のサイズを解釈できません（値: %r）。ダウンロードサイズの検証を行いません。",
        file_name,
        raw_size,
    )
    return None


def extract_listing_entries(listing: dict[str, Any]) -> list[TileFile]:
    """LAADS の一覧レスポンスからファイル情報を取り出す。

    ダウンロード URL は**自前で組み立てず、一覧が返す `downloadsLink` を使う**。
    アーカイブの公開パス（`/archive/allData/...`）はライセンス同意ページへ 303 され、
    Bearer トークンでは辿れない。実際に配信されるのは API 側の
    `/api/v2/content/archives/allData/...` で、これは一覧が教えてくれる。

    Args:
        listing: 一覧 API のレスポンス（JSON をパースした辞書）。

    Returns:
        ファイル情報のリスト。

    Raises:
        RuntimeError: 想定した構造でない場合。
    """
    entries = listing.get("content")
    if not isinstance(entries, list):
        raise RuntimeError(
            "LAADS の一覧レスポンスに content 配列がありません"
            f"（トップレベルのキー: {sorted(listing)}）。"
        )

    tile_files: list[TileFile] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("fileName")
        download_url = entry.get("downloadsLink")
        if not (isinstance(name, str) and name):
            continue
        if not is_safe_tile_file_name(name):
            # 名前はそのままキャッシュのパスになるため、保存先の外を指しうる値は使わない
            logger.warning(
                "一覧のファイル名がパスとして安全ではありません。対象から外します: %r", name
            )
            continue
        if not (isinstance(download_url, str) and download_url):
            # URL が無いと取得できない。件数だけ合っていても意味がないため落とさず記録する
            logger.warning("一覧の %s に downloadsLink がありません。対象から外します。", name)
            continue
        if not is_safe_download_url(download_url):
            # トークンを添えて叩く先のため、想定外のホスト・スキームは使わない
            logger.warning(
                "一覧の %s の downloadsLink が想定外の宛先です。対象から外します: %r",
                name,
                download_url,
            )
            continue
        tile_files.append(
            TileFile(
                name=name,
                download_url=download_url,
                size_bytes=parse_listing_size(entry.get("size"), name),
            )
        )

    if not tile_files:
        raise RuntimeError(
            f"LAADS の一覧からファイル情報を取り出せませんでした（件数: {len(entries)}）。"
        )
    return tile_files


def select_tile_files(tile_files: list[TileFile], tiles: list[TileIndex]) -> dict[str, TileFile]:
    """ファイル一覧から、必要なタイルのファイルだけを選ぶ。

    VNP46A4 のファイル名は `VNP46A4.A{年}001.h28v06.002.{生成日時}.h5` 形式で、
    生成日時は事前に分からない。そのためタイル名を含むかどうかで選ぶ。

    Args:
        tile_files: 一覧から得た全ファイル情報。
        tiles: 必要なタイル。

    Returns:
        タイル名 -> ファイル情報。

    Raises:
        RuntimeError: 必要なタイルが一覧に無い場合、または同一タイルが複数ある場合。
    """
    selected: dict[str, TileFile] = {}
    for tile in tiles:
        matched = [tile_file for tile_file in tile_files if f".{tile.name}." in tile_file.name]
        if not matched:
            raise RuntimeError(
                f"タイル {tile.name} のファイルが一覧にありません"
                f"（一覧の件数: {len(tile_files)}）。"
            )
        if len(matched) > 1:
            # 同一タイルの再処理版が併存すると、どちらを使ったか分からなくなる
            raise RuntimeError(
                f"タイル {tile.name} のファイルが複数あります: "
                f"{sorted(tile_file.name for tile_file in matched)}。"
                "使用する版を特定できないため停止します。"
            )
        selected[tile.name] = matched[0]
    return selected
