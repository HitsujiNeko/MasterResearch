"""Google Earth Engine（GEE）の認証・初期化処理。

複数のGEE利用スクリプトで重複していた認証フォールバック処理・
プロジェクトID解決処理を集約する。
"""

from __future__ import annotations

import logging
from pathlib import Path

import ee
import pandas as pd

logger = logging.getLogger(__name__)


def authenticate_gee(project_id: str) -> None:
    """Google Earth Engineを認証・初期化する。

    まず `ee.Initialize` を試行し、失敗した場合は `ee.Authenticate` による
    ブラウザ認証を経て再度 `ee.Initialize` する。

    Args:
        project_id: Google Cloud Platform プロジェクトID。

    Raises:
        Exception: 認証フォールバックを含めても初期化に失敗した場合。
    """
    try:
        ee.Initialize(project=project_id)
        logger.info(f"GEEはすでに認証されています（プロジェクト: {project_id}）")
    except Exception:
        logger.info("GEEを認証しています…")
        try:
            ee.Authenticate()
            ee.Initialize(project=project_id)
            logger.info(f"GEE認証に成功しました（プロジェクト: {project_id}）")
        except Exception as exc:
            logger.error(f"GEE認証エラー: {exc}")
            raise


def load_gee_project_id(config_path: Path, explicit_project_id: str = "") -> str:
    """GEEプロジェクトIDを取得する。

    明示指定を優先し、指定がなければ設定CSVの `gee_project_id` 列から取得する。

    Args:
        config_path: GEE設定CSVのパス。
        explicit_project_id: 明示的に指定されたプロジェクトID。

    Returns:
        解決済みのGEEプロジェクトID。

    Raises:
        FileNotFoundError: 設定CSVが存在しない場合。
        ValueError: 設定CSVが空、またはプロジェクトIDが未設定・プレースホルダのままの場合。
    """
    if explicit_project_id.strip():
        return explicit_project_id.strip()

    if not config_path.exists():
        raise FileNotFoundError(f"GEE設定CSVが見つかりません: {config_path}")

    config_df = pd.read_csv(config_path)
    if config_df.empty:
        raise ValueError(f"GEE設定CSVが空です: {config_path}")

    raw_value = config_df.iloc[0].get("gee_project_id", "")
    project_id = "" if pd.isna(raw_value) else str(raw_value).strip()
    if not project_id or project_id == "YOUR_GCP_PROJECT_ID":
        raise ValueError(
            "GEEプロジェクトIDが取得できませんでした。"
            "explicit_project_id を指定するか設定CSVを確認してください。"
        )
    return project_id
