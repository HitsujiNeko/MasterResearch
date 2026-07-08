---
name: check-drive-sync
description: "Google Drive の MasterResearch フォルダとローカル data/ ディレクトリの構成を比較し、共有漏れ・配置漏れを検出して差分レポートを提示する。「Drive同期チェック」「共有漏れの確認」「Driveとdataの差分を見て」などのリクエストで使用する。"
---

# Google Drive / data 同期チェックスキル

Google Drive とローカル `data/` の2層運用（`docs/02_methods/data_management_guide.md`）における同期状況を検査する。
**検出と報告のみを行い、ファイルの転送・削除は行わない**（フェーズ1）。

## 対象範囲

| 対象 | 理由 |
|---|---|
| `data/satellite/`, `data/gis/`, `data/BSHorizon/` | Git 管理外の大容量データ。Drive が共有経路 |
| 対象外: `data/input/`, `data/output/` | Git で管理するため Drive 同期不要 |

## 実行手順

### Step 1: Drive 側インベントリの取得

Google Drive MCP の `search_files` ツールを使う。

1. ルートフォルダの特定:
   - クエリ `title = 'MasterResearch' and mimeType = 'application/vnd.google-apps.folder'`
   - 複数ヒットした場合は `viewUrl` をユーザーに提示して選択してもらう
2. フォルダ走査（幅優先）:
   - 各フォルダに対し `parentId = '{フォルダID}'` で子要素を取得する
   - `nextPageToken` があれば追加ページを取得する（取得漏れ防止）
   - `mimeType = 'application/vnd.google-apps.folder'` はキューに追加、それ以外はファイルとして「相対パス（`親フォルダ名/.../ファイル名`）」を記録する
3. 結果を「Drive相対パスの一覧」として整理する

### Step 2: ローカル側インベントリの取得

対象4ディレクトリを走査し、相対パス一覧を作る（存在しないディレクトリはスキップし、その旨を記録）。

```powershell
Get-ChildItem -Recurse -File data/satellite, data/gis, data/BSHorizon |
  ForEach-Object { $_.FullName.Replace((Get-Location).Path + '\', '').Replace('\', '/') }
```

補助ファイル（`*.aux`, `*.aux.xml`, サムネイル等）は比較から除外する。

### Step 3: 差分の算出

相対パス（`data/` プレフィックスと Drive の `MasterResearch/` プレフィックスを揃えて）で突合する。

- **共有漏れ**: ローカルにあり Drive にないファイル
- **配置漏れ**: Drive にありローカルにないファイル
- **トップレベル欠落**: Drive に対象ディレクトリ自体が存在しない場合は個別ファイルを列挙せず「ディレクトリごと未共有」として報告する

日本語ファイル名を含む一覧の処理は、一時ファイルに書き出して UTF-8 指定で読み書きする（パイプ直結の文字化け対策）。

### Step 4: 差分レポートの提示

以下の形式でユーザーに提示する。

```markdown
## Drive 同期チェック結果（YYYY-MM-DD）

- ローカル対象ファイル数: {n} / Drive ファイル数: {n}

### 📤 共有漏れ（ローカルのみ・{n}件）
- data/... （ディレクトリごとの件数サマリー + 代表例。多い場合は上位20件）

### 📥 配置漏れ（Driveのみ・{n}件）
- MasterResearch/...

### ✅ 同期済み: {n}件
```

差分が0件の場合は「同期OK」と報告して終了する。

### Step 5: 次のアクションの提案

- 共有漏れ → Google Drive for desktop / ブラウザでの手動アップロードを案内する（対象パス一覧を提示）
- 配置漏れ → ダウンロードすべきファイルの一覧を提示する
- **MCP経由のファイル転送は行わない**: Drive MCP の読み書きツールはファイル内容がモデルのコンテキストを経由する設計のため、大容量バイナリ（GeoTIFF/GPKG）の転送には適さない。転送は Google Drive for desktop 等の同期クライアントで行う

## 注意事項

- 本スキルは読み取り専用。Drive・ローカルの双方に対して作成・削除・変更を行わない
- ファイルサイズ・更新日時の照合はフェーズ1では行わない（存在の有無のみ）。内容の同一性が疑わしい場合はユーザーに手動確認を案内する
- Drive のフォルダ数が多い場合は走査に時間がかかるため、対象ディレクトリを絞った部分チェックも可能（ユーザー指定）
