"""相対パスの解決と入出力パスの検証処理を集約する。

複数の取得・分析スクリプトで重複していた
「相対パスをプロジェクトルート基準で解決し、存在確認・ディレクトリ作成を行う」処理と、
「サマリー出力用にプロジェクト相対パスの文字列へ変換する」処理をここに集約する。
"""

from __future__ import annotations

from pathlib import Path

from src.common.config import PROJECT_ROOT


def resolve_relative_to_project_root(value: str, project_root: Path = PROJECT_ROOT) -> Path | None:
    """CLI引数などの相対パス文字列をプロジェクトルート基準で絶対化する。

    存在確認や親ディレクトリ作成は行わない純粋なパス解決であり、入力ファイルの
    要否・出力ディレクトリの作成要否は呼び出し側が個別に判断する
    （``resolve_existing_path()`` / ``prepare_output_path()`` と役割分担する）。
    「未指定なら既定パスを使う」という判断も、既定パスの中身が呼び出し元ごとに
    異なるため、ここでは行わず呼び出し側に委ねる。

    **``project_root`` は呼び出し側で明示的に渡すこと。** 既定値はこの関数の
    定義時に一度だけ評価されるため、呼び出し元モジュールが自身の ``PROJECT_ROOT``
    を ``monkeypatch`` で差し替えても（テストでのプロジェクトルート隔離等）、
    この関数の既定値には反映されない。呼び出し元が自身の（monkeypatch可能な）
    ``PROJECT_ROOT`` を ``project_root=`` として明示的に渡すことで、呼び出し時点の
    値を使わせる。

    Args:
        value: CLI引数などで受け取ったパス文字列。空文字は「未指定」を表す。
        project_root: 相対パスの基準ディレクトリ。呼び出し元の ``PROJECT_ROOT``
            を明示的に渡すことを推奨する（上記参照）。

    Returns:
        絶対化した ``Path``。``value`` が空文字の場合は ``None``
        （呼び出し側が既定値を決める）。
    """
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else (project_root / path)


def resolve_existing_path(path: Path, project_root: Path = PROJECT_ROOT) -> Path:
    """相対パスをプロジェクトルート基準で解決し、存在確認を行う。

    Args:
        path: 解決対象のパス（絶対パスの場合はそのまま使う）。
        project_root: 相対パスの基準ディレクトリ。
    Returns:
        存在確認済みの絶対パス。
    """
    resolved = path if path.is_absolute() else (project_root / path)
    resolved = resolved.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {resolved}")
    return resolved


def prepare_output_path(path: Path, project_root: Path = PROJECT_ROOT) -> Path:
    """相対パスをプロジェクトルート基準で解決し、出力先ディレクトリを作成する。

    Args:
        path: 解決対象のパス（絶対パスの場合はそのまま使う）。
        project_root: 相対パスの基準ディレクトリ。
    Returns:
        親ディレクトリ作成済みの絶対パス。
    """
    resolved = path if path.is_absolute() else (project_root / path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved.resolve()


def to_project_relative_string(path: Path, project_root: Path = PROJECT_ROOT) -> str:
    """可能ならプロジェクト相対パスの文字列へ変換する。

    サマリー JSON へ絶対パスを残さないための変換で、
    プロジェクトルート外のパスは絶対パスのまま返す。
    区切り文字は実行 OS によらず `/` に統一する（Windows で生成したサマリーを
    他環境で読んだときにパスが解釈できなくなるのを避けるため）。

    Args:
        path: 変換対象パス。
        project_root: 相対化の基準ディレクトリ。
    Returns:
        プロジェクト相対パス、またはルート外の場合は絶対パスの文字列。
    """
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(project_root).as_posix()
    except ValueError:
        return resolved_path.as_posix()
