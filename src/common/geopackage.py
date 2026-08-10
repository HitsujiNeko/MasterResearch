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


def replace_geopackage(temp_path: Path, output_path: Path) -> None:
    """書き出し済みの一時GeoPackageを出力先へ差し替える。

    ``Path.replace()`` は同一ディレクトリ（＝同一ファイルシステム）でアトミックに
    動作するため、途中で失敗しても既存の出力はそのまま残る。差し替えの前に出力先の
    付随ファイルを消すのは、本体だけを差し替えると別のデータベースの ``-wal`` /
    ``-shm`` が残った状態になるためである。

    **Windowsでは、出力先をQGIS等が開いたままだと差し替えが失敗する。** 素の
    ``PermissionError`` は原因を読み取りにくいため、対処を示す日本語のメッセージへ
    包み直す。生成済みの一時ファイルは消さずに残し、手動で回収できるようにする。

    Args:
        temp_path: 書き出し済みの一時GeoPackageのパス。
        output_path: 差し替え先のGeoPackageパス。

    Raises:
        OSError: 差し替えに失敗した場合。元の例外は ``__cause__`` に保持する。
    """
    remove_sidecar_files(output_path)
    try:
        Path(temp_path).replace(output_path)
    except OSError as error:
        raise OSError(
            f"出力先への差し替えに失敗しました: {output_path}。"
            " 出力先のファイルがQGISなど他のアプリケーションで開かれていないか確認してください。"
            f" 書き出し済みの一時ファイルは残しています: {temp_path}"
        ) from error
