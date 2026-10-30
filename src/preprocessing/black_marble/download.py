"""タイルファイルの取得・キャッシュと、ライセンス未同意の切り分け。

取得した内容・キャッシュが本当に HDF5 かを署名で確かめ、未認証時の HTML が
キャッシュに焼き付くのを防ぐ。
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.common.http_fetch import fetch_bytes_with_retry
from src.preprocessing.black_marble.listing import (
    ALLOWED_DOWNLOAD_HOSTS,
    ALLOWED_REDIRECT_HOSTS,
    LISTING_TIMEOUT_SECONDS,
    TileFile,
    is_safe_download_url,
)
from src.preprocessing.black_marble.product import PRODUCT_NAME

logger = logging.getLogger(__name__)

# タイル本体は 100MB 超のため、一覧取得（`LISTING_TIMEOUT_SECONDS`）とは別のタイムアウトを与える
DOWNLOAD_TIMEOUT_SECONDS = 1800

# ライセンス未同意時のリダイレクト先に現れるパス断片
LICENSE_PATH_MARKER = "/profiles/licenses/"

# HDF5 の先頭 8 バイト（署名）。取得結果・キャッシュが本当に HDF5 かの判定に使う。
# 未認証時の LAADS はログインページの HTML を HTTP 200 で返すため、内容を見ないと
# 「.h5 という名前の HTML」がキャッシュに焼き付き、トークンを直しても復旧しない。
HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"


def find_license_gate(download_url: str, headers: dict[str, str]) -> str | None:
    """ダウンロードがライセンス未同意で止められていないかを調べる。

    LAADS はデータ利用許諾が未同意の製品に対し、401 ではなく
    `/profiles/licenses/...` への 303 を返す。リダイレクトを辿ると最終的に
    Earthdata の OAuth で 401 になるため、素のエラーからは原因が分からない。
    失敗時にだけ呼び、原因を切り分けるために使う。

    Args:
        download_url: 調べる URL。
        headers: 認証ヘッダー。

    Returns:
        ライセンス同意ページの URL。ライセンスが原因でなければ None。
        URL が想定外の宛先の場合も None（トークンを送らずに打ち切る）。
    """
    if not is_safe_download_url(download_url):
        # 認証ヘッダーを付けて開くため、想定外の宛先は確認そのものを行わない
        logger.warning("想定外の宛先のためライセンス確認を行いません: %r", download_url)
        return None

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        """リダイレクトを追わず、Location をそのまま観察するためのハンドラ。"""

        def redirect_request(
            self,
            req: urllib.request.Request,
            fp: Any,
            code: int,
            msg: str,
            response_headers: Any,
            newurl: str,
        ) -> None:
            """None を返してリダイレクトの追跡を止める。

            Args:
                req: 元のリクエスト。
                fp: レスポンスのファイルオブジェクト。
                code: HTTP ステータスコード。
                msg: ステータスメッセージ。
                response_headers: レスポンスヘッダー。
                newurl: リダイレクト先 URL。

            Returns:
                常に None（urllib はこれを受けて追跡を打ち切る）。
            """
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(download_url, headers=headers)
    try:
        with opener.open(request, timeout=LISTING_TIMEOUT_SECONDS):
            return None
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location") or ""
        if LICENSE_PATH_MARKER in location:
            return urllib.parse.urljoin(download_url, location)
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        # 切り分けのための補助的な確認なので、ここでの失敗は握って呼び出し元の
        # 元エラーを優先させる
        return None


def looks_like_hdf5(head: bytes) -> bool:
    """先頭バイト列が HDF5 の署名で始まるかを判定する。

    Args:
        head: ファイル・レスポンスの先頭バイト列（8 バイト以上）。

    Returns:
        HDF5 として読める見込みがあれば True。
    """
    return head.startswith(HDF5_SIGNATURE)


def download_tile(
    tile_file: TileFile,
    destination_path: Path,
    headers: dict[str, str],
) -> Path:
    """タイルファイルをダウンロードして保存する（既存ならそのまま使う）。

    1 タイル 100MB 超のため、既に取得済みなら再取得しない。書き込みは一時ファイルへ
    行ってから差し替える（中断で壊れたファイルがキャッシュに残るのを防ぐ）。

    **保存前に中身が HDF5 であることとサイズを検証する**。未認証・トークン失効時の
    LAADS は 401 ではなくログインページの HTML を HTTP 200 で返すため、内容を見ずに
    保存すると「`.h5` という名前の HTML」がキャッシュに焼き付く。以降は取得済み
    扱いで即 return するため、トークンを再発行しても HDF5 の署名エラーで失敗し
    続け、手動でキャッシュを消すまで復旧しない。同じ理由で、既にキャッシュされて
    いるファイルも署名を確認し、壊れていれば破棄して取り直す。

    失敗した場合はライセンス未同意かどうかを切り分け、該当すれば同意ページの URL を
    添えて投げ直す（リダイレクト先の 401 のままでは原因が分からないため）。

    Args:
        tile_file: 一覧から得たファイル情報。
        destination_path: 保存先パス。
        headers: 認証ヘッダー。

    Returns:
        保存したパス。

    Raises:
        RuntimeError: ダウンロードに失敗した場合、取得した内容が HDF5 でない・
            サイズが一覧の値と一致しない場合、またはダウンロード URL が
            想定外の宛先の場合。
    """
    if not is_safe_download_url(tile_file.download_url):
        # 一覧の解析側でも弾いているが、トークンの送信先はこの関数の入口でも確かめる
        raise RuntimeError(
            f"ダウンロード URL が想定外の宛先です（{tile_file.name}）: {tile_file.download_url!r}。"
            f"許可しているホスト: {sorted(ALLOWED_DOWNLOAD_HOSTS)}"
        )

    if destination_path.exists():
        with destination_path.open("rb") as cached_file:
            cached_head = cached_file.read(len(HDF5_SIGNATURE))
        if looks_like_hdf5(cached_head):
            logger.info(
                "取得済みのタイルを使います（%.1f MB）: %s",
                destination_path.stat().st_size / 1_000_000,
                destination_path.name,
            )
            return destination_path
        # 残したままだと取得済み扱いで永久に復旧しないため、捨てて取り直す
        logger.warning(
            "キャッシュが HDF5 ではありません（認証切れ時の HTML の可能性）。"
            "破棄して取り直します: %s",
            destination_path.name,
        )
        destination_path.unlink()

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    size_text = (
        "サイズ不明"
        if tile_file.size_bytes is None
        else f"約 {tile_file.size_bytes / 1_000_000:.0f} MB"
    )
    logger.info("タイルをダウンロードします（%s）: %s", size_text, destination_path.name)
    try:
        response_body = fetch_bytes_with_retry(
            tile_file.download_url,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            headers=headers,
            allowed_redirect_hosts=ALLOWED_REDIRECT_HOSTS,
        )
    except RuntimeError as exc:
        license_url = find_license_gate(tile_file.download_url, headers)
        if license_url is None:
            raise
        raise RuntimeError(
            f"{PRODUCT_NAME} のデータ利用許諾が未同意のためダウンロードできません。"
            "ブラウザで Earthdata にログインした状態で次の URL を開き、"
            f"許諾に同意してから再実行してください: {license_url}"
        ) from exc

    if not looks_like_hdf5(response_body):
        preview = response_body[:200].decode("utf-8", errors="replace")
        raise RuntimeError(
            "ダウンロードした内容が HDF5 ではありません。Earthdata のトークンが無効・"
            "期限切れか、データ利用許諾が未同意の可能性があります"
            "（未認証だとログインページの HTML が HTTP 200 で返ります）。"
            "壊れた内容をキャッシュへ焼き付けないよう、保存はしていません。"
            f"応答の先頭: {preview!r}"
        )
    if tile_file.size_bytes is not None and len(response_body) != tile_file.size_bytes:
        raise RuntimeError(
            "ダウンロードしたサイズが一覧の値と一致しません"
            f"（一覧: {tile_file.size_bytes} バイト、取得: {len(response_body)} バイト）。"
            "転送が途中で切れた可能性があるため、保存はしていません。"
        )

    temporary_path = destination_path.with_suffix(destination_path.suffix + ".part")
    temporary_path.write_bytes(response_body)
    temporary_path.replace(destination_path)
    logger.info("ダウンロード完了（%.1f MB）", len(response_body) / 1_000_000)
    return destination_path
