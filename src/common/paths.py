"""相対パスの解決と入出力パスの検証処理を集約する。

複数の取得・分析スクリプトで重複していた
「相対パスをプロジェクトルート基準で解決し、存在確認・ディレクトリ作成を行う」処理と、
「サマリー出力用にプロジェクト相対パスの文字列へ変換する」処理をここに集約する。
"""

from __future__ import annotations

from pathlib import Path

from src.common.config import PROJECT_ROOT


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

    Args:
        path: 変換対象パス。
        project_root: 相対化の基準ディレクトリ。
    Returns:
        プロジェクト相対パス、またはルート外の場合は絶対パスの文字列。
    """
    resolved_path = path.resolve()
    try:
        return str(resolved_path.relative_to(project_root))
    except ValueError:
        return str(resolved_path)
