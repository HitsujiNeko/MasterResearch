# QGIS MCP セットアップガイド

**最終更新**: 2026-08-04  
**関連ドキュメント**: [../setup.md](../setup.md), [../02_methods/CodingRule.md](../02_methods/CodingRule.md), [../02_methods/data_management_guide.md](../02_methods/data_management_guide.md), [../02_methods/qgis_mcp_usage_guide.md](../02_methods/qgis_mcp_usage_guide.md), [../02_methods/qgis_operation_guidelines.md](../02_methods/qgis_operation_guidelines.md)  
**前提知識**: Claude Code の基本操作、QGIS の基本操作

---

## 概要

[nkarasiak/qgis-mcp](https://github.com/nkarasiak/qgis-mcp) を使用して、Claude Code から QGIS を直接操作できる環境を構築する。

**主な用途**:

- データ収集・加工スクリプトの出力を QGIS で目視確認
- レイヤー操作・Processing アルゴリズムの会話ベース実行
- 地図データの視覚的な品質チェック

**アーキテクチャ**:

```text
Claude Code <-- stdio (MCP) --> MCP Server (uvx) <-- TCP socket --> QGIS Plugin
```

## 動作要件

| 要件 | バージョン |
|------|-----------|
| QGIS | 3.28 以上（4.x 含む） |
| uv パッケージマネージャー | 最新版 |
| Python | 3.12（MCP サーバー用） |

## セットアップ手順

### 1. QGIS プラグインのインストール

1. QGIS を起動
2. `プラグイン` → `プラグインの管理とインストール` → `全プラグイン` タブ
3. 「QGIS MCP」を検索し、**Nicolas Karasiak** 作のプラグインを `.mcp.json` に記載のサーバーと**同一バージョン**でインストール
4. QGIS を再起動

> **バージョンの正本は `.mcp.json`**。本ガイドには具体的な版数を書かない（二重管理になり、片方が取り残されるため）。サーバーとプラグインの版数が一致しているかは `diagnose` の `version_match` で確認する（後述の「5. 接続テスト」を参照）。更新の要否判断・手順は [qgis_operation_guidelines.md の「QGIS-MCP の既知の制約と回避策」](../02_methods/qgis_operation_guidelines.md#qgis-mcp-の既知の制約と回避策)を正本とする。

> **注意**: jjsantos01/qgis_mcp（バージョン 1.0）とは別物。作者が Nicolas Karasiak であることを確認すること。  
> jjsantos01 版が残っている場合、プロトコル不一致（改行区切り JSON vs length-prefixed framing）により接続に失敗する。

### 2. MCP サーバーの設定

プロジェクトルートの `.mcp.json` に設定済み。新しい PC で clone した場合、追加作業は不要。

以下は**構造を示す例**であり、参照タグの実際の版数は `.mcp.json` の現物を参照する。

```jsonc
// .mcp.json（vX.Y.Z の部分は実際の値を .mcp.json で確認する）
{
  "mcpServers": {
    "qgis": {
      "command": "uvx",
      "args": [
        "--python", "3.12",
        "--from",
        "https://github.com/nkarasiak/qgis-mcp/archive/refs/tags/vX.Y.Z.zip",
        "qgis-mcp-server"
      ],
      "env": {
        "QGIS_MCP_HOST": "127.0.0.1",
        "QGIS_MCP_PORT": "9876"
      }
    }
  }
}
```

> **`command` フィールドについて**: `"uvx"` で動作しない場合は、`uvx.exe` のフルパス（例: `C:\\Users\\<ユーザー名>\\.local\\bin\\uvx.exe`）に変更する。

### 3. QGIS サーバーの起動

1. QGIS を起動
2. Dock ウィジェット「QGIS MCP」でポートを **9876** に設定
3. 「**Start Server**」をクリック
4. ステータスに「Server: Running on port 9876」と表示されることを確認

### 4. Claude Code の再起動

VSCode の場合、以下のいずれかで MCP サーバーを認識させる：

- コマンドパレット（`Ctrl+Shift+P`）→「Claude Code: Restart Extension」
- VSCode 自体を再起動

### 5. 接続テスト

Claude Code のチャットで以下のように指示する：

```text
QGIS に ping して
```

`{"pong": true}` が返れば接続成功。

続けて `diagnose` を実行し、`version_match` が `ok`（`server` と `plugin` が同一版数）・`status` が `healthy` であることを確認する。ここが `mismatch` の場合は、プラグインとサーバーのどちらかが古い。

```text
QGIS に diagnose して
```

> **`.mcp.json` を書き換えただけではサーバーは切り替わらない**。Claude Code を再起動するまで旧バージョンのサーバーが動き続け、新しいツールは一覧に現れない。

## 使用時の注意

- **QGIS が起動中かつサーバーが稼働中でないと接続できない**。QGIS を閉じると MCP 接続が切れる
- QGIS のプロジェクトを開いた状態でないとレイヤー操作が反映されない場合がある
- MCP サーバープロセスは Claude Code が自動的に起動・管理する。手動起動は不要

## トラブルシューティング

### 「Socket operation timed out after 30s」

**原因と対処**:

1. **QGIS サーバーが起動していない** → Dock ウィジェットで「Start Server」を押す
2. **ポート不一致** → QGIS 側のポートが 9876 であることを確認。`.mcp.json` の `QGIS_MCP_PORT` と一致させる
3. **古い MCP サーバープロセスが残っている** → タスクマネージャーで `qgis-mcp-server` プロセスをすべて終了し、VSCode を再起動
4. **プラグインバージョン不一致** → `diagnose` の `version_match` を確認する。`mismatch`（`server` と `plugin` の版数が異なる）の場合は、`.mcp.json` に記載のバージョンに合わせてプラグインを入れ替え、QGIS と Claude Code を再起動する

### ポート 9876 への TCP 接続を確認する方法

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 9876
```

`TcpTestSucceeded: True` であれば QGIS サーバーは起動している。

## 主要ツール一覧（抜粋）

| ツール | 用途 |
|--------|------|
| `ping` | 接続確認 |
| `add_vector_layer` | ベクターレイヤーの読み込み |
| `add_raster_layer` | ラスターレイヤーの読み込み |
| `get_layers` | レイヤー一覧の取得 |
| `zoom_to_layer` | レイヤー範囲にズーム |
| `set_layer_style` | レイヤーのスタイル設定（分類・段階区分） |
| `execute_processing` | Processing アルゴリズムの実行 |
| `render_map` | 地図のレンダリング（画像として取得） |
| `get_canvas_screenshot` | キャンバスのスクリーンショット |
| `execute_code` | 任意の PyQGIS コード実行 |

全ツール一覧は上流 README を参照する。ただし**`.mcp.json` の参照タグと同じタグの README を開くこと**（[タグ一覧](https://github.com/nkarasiak/qgis-mcp/tags)から選ぶ）。既定ブランチの README は固定版に存在しないツールを含みうるため、そのまま使うと操作が失敗する。ツール数は上流の更新で増えるため本ガイドには記載しない。

上流由来の制約・使えるようになった機能の採否は [qgis_operation_guidelines.md の「QGIS-MCP の既知の制約と回避策」](../02_methods/qgis_operation_guidelines.md#qgis-mcp-の既知の制約と回避策)を参照。
