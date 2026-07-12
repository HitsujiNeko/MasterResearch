"""相対パスの解決と入出力パスの検証処理を集約する。

`src/preprocessing/` 配下の複数スクリプトで重複していた
「相対パスをプロジェクトルート基準で解決し、存在確認・ディレクトリ作成を行う」
処理をここに集約する。
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
