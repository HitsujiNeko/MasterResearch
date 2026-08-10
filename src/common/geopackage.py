"""GeoPackage ファイルの後片付けに関する共通処理をまとめたモジュール。

GeoPackage の実体は SQLite データベースであり、書き込み中に中断すると
``-wal`` / ``-shm`` / ``-journal`` といった付随ファイルが残ることがある。本体だけを
削除・差し替えすると、次に同名で作ったデータベースに古い付随ファイルが残留した
状態になるため、本体と付随ファイルは常に組で扱う必要がある。

一時ファイルへ書き出して ``Path.replace()`` で差し替える出力処理は複数のモジュールに
あり、いずれも同じ後片付けを必要とするため、ここへ集約する。
"""

from __future__ import annotations

from pathlib import Path

# SQLite が GeoPackage 本体と併せて生成しうる付随ファイルの接尾辞。
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def remove_sidecar_files(path: Path) -> None:
    """GeoPackage本体は残し、付随ファイルだけを削除する。

    一時ファイルを ``Path.replace()`` で出力先へ差し替える直前に使う。本体だけを
    差し替えると、出力先に残っていた別のデータベースの付随ファイルが引き継がれて
    しまうためである。

    Args:
        path: 対象GeoPackageのパス。付随ファイルが無い場合は何もしない。
    """
    for suffix in SIDECAR_SUFFIXES:
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def remove_geopackage(path: Path) -> None:
    """GeoPackage本体とSQLiteの付随ファイルをまとめて削除する。

    書きかけの一時ファイルを片付ける用途で使う。

    Args:
        path: 削除するGeoPackageのパス。存在しない場合は何もしない。
    """
    Path(path).unlink(missing_ok=True)
    remove_sidecar_files(path)
