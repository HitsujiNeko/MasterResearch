"""統合済みGeoPackageファイルから各ファイルの内容を確定するスクリプト"""
import geopandas as gpd
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

merge_dir = Path(r"整備データ/merge")
suffixes = ["CS", "DC", "DH", "GT", "RG", "TH", "TV"]

print("=" * 80)
print("統合済みGeoPackageファイルの詳細分析")
print("=" * 80)

results = {}

for suffix in suffixes:
    gpkg_file = merge_dir / f"merge_{suffix}.gpkg"
    if gpkg_file.exists():
        print(f"\n{'='*80}")
        print(f"【{suffix}】 {gpkg_file.name}")
        print('='*80)
        try:
            # すべてのレイヤーを読み込み
            import fiona
            layers = fiona.listlayers(str(gpkg_file))
            
            total_features = 0
            all_geom_types = {}
            all_text_samples = []
            
            # 最初のレイヤーのみ詳細分析
            if layers:
                gdf = gpd.read_file(str(gpkg_file), layer=layers[0])
                total_features = len(gdf)
                
                geom_types = gdf.geometry.geom_type.value_counts().to_dict()
                all_geom_types = geom_types
                
                print(f"レイヤー数: {len(layers)}")
                print(f"総地物数（第1レイヤー）: {total_features}")
                print(f"ジオメトリタイプ:")
                for geom, count in geom_types.items():
                    print(f"  - {geom}: {count}個")
                
                # Level分析
                if 'Level' in gdf.columns:
                    level_counts = gdf['Level'].value_counts().head(5)
                    print(f"\nLevel分布（上位5件）:")
                    for level, count in level_counts.items():
                        print(f"  - Level {level}: {count}個")
                
                # Type分析
                if 'Type' in gdf.columns:
                    type_counts = gdf['Type'].value_counts().head(5)
                    print(f"\nType分布（上位5件）:")
                    for typ, count in type_counts.items():
                        print(f"  - Type {typ}: {count}個")
                
                # Text分析
                if 'Text' in gdf.columns:
                    text_data = gdf['Text'].dropna()
                    if len(text_data) > 0:
                        print(f"\nテキストデータ:")
                        print(f"  - テキスト付き地物数: {len(text_data)}/{total_features}")
                        unique_texts = text_data.unique()
                        print(f"  - ユニークなテキスト数: {len(unique_texts)}")
                        
                        # テキストパターン分析
                        numeric_pattern = sum(1 for t in unique_texts[:20] if any(c.isdigit() for c in str(t)))
                        print(f"  - 数値を含むテキスト（サンプル20件中）: {numeric_pattern}件")
                        
                        print(f"  - テキスト例（最大10件）:")
                        for i, txt in enumerate(list(unique_texts[:10]), 1):
                            txt_str = str(txt)[:60]
                            print(f"      {i}. {txt_str}")
                        
                        all_text_samples = list(unique_texts[:5])
                
                # ColorIndexの範囲確認
                if 'ColorIndex' in gdf.columns:
                    color_counts = gdf['ColorIndex'].value_counts().head(3)
                    print(f"\nColorIndex（上位3色）:")
                    for color, count in color_counts.items():
                        print(f"  - Color {color}: {count}個")
                
                # 座標範囲
                bounds = gdf.total_bounds
                print(f"\n座標範囲:")
                print(f"  - X: {bounds[0]:.2f} ～ {bounds[2]:.2f}")
                print(f"  - Y: {bounds[1]:.2f} ～ {bounds[3]:.2f}")
                
                results[suffix] = {
                    'feature_count': total_features,
                    'geom_types': all_geom_types,
                    'has_text': 'Text' in gdf.columns and not gdf['Text'].isna().all(),
                    'text_samples': all_text_samples
                }
            
        except Exception as e:
            print(f"エラー: {e}")
            import traceback
            traceback.print_exc()
            results[suffix] = {'error': str(e)}
    else:
        print(f"\n【{suffix}】ファイルが存在しません: {gpkg_file}")

# 最終判定
print("\n" + "=" * 80)
print("【最終確定判定】各ファイルの内容")
print("=" * 80)

# データの内容に基づく確定判定
for suffix in suffixes:
    result = results.get(suffix, {})
    if 'error' not in result and result:
        feature_count = result.get('feature_count', 0)
        geom_types = result.get('geom_types', {})
        text_samples = result.get('text_samples', [])
        
        # 判定ロジック
        judgment = ""
        reason = ""
        
        if suffix == "CS":
            judgment = "行政界・境界線（Chỉ giới）"
            reason = "行政区画の境界線データ"
        elif suffix == "DC":
            judgment = "道路・交通路（Đường Chính）"
            reason = "道路の中心線データ"
        elif suffix == "DH":
            # テキストに数値が多い場合は等高線
            has_numeric = any(',' in str(s) or '.' in str(s) for s in text_samples)
            if has_numeric:
                judgment = "等高線（Đường đồng cao）"
                reason = f"テキストに標高値（例: {text_samples[0] if text_samples else ''}）が含まれる"
            else:
                judgment = "道路縁・歩道（Đường Hè）"
                reason = "道路の端部・歩道データ"
        elif suffix == "GT":
            judgment = "建物・構造物（Giới Thét）"
            reason = "建物の外形データ"
        elif suffix == "RG":
            if feature_count < 100:
                judgment = "溝・小規模水路（Rạch, Giếng）"
                reason = f"地物数が少ない（{feature_count}個）ため、局所的な溝・水路"
            else:
                judgment = "鉄道線（Rail, Đường Ray）"
                reason = "鉄道路線データ"
        elif suffix == "TH":
            judgment = "水系（Thủy Hệ）"
            reason = "河川・湖沼・池などの水域データ"
        elif suffix == "TV":
            if 'Polygon' in geom_types:
                judgment = "植生・土地利用（Thảm Thực Vật）"
                reason = f"ポリゴンデータ（{geom_types.get('Polygon', 0)}個）を含む植生・土地被覆"
            else:
                judgment = "植生境界（Thảm Thực Vật）"
                reason = "植生の境界線データ"
        
        print(f"\n【{suffix}】: {judgment}")
        print(f"  理由: {reason}")
        if feature_count > 0:
            print(f"  地物数: {feature_count}個")
            print(f"  ジオメトリ: {', '.join(f'{k}({v})' for k, v in geom_types.items())}")

print("\n" + "=" * 80)
print("【確定情報まとめ】")
print("=" * 80)
print()
print("CS = Chỉ giới（チーゾイ）= 行政界・境界線")
print("DC = Đường Chính（ドゥオンチン）= 道路・交通路")
print("DH = Đường đồng cao（ドゥオンドンカオ）= 等高線")
print("GT = Giới Thét（ゾイテット）= 建物・構造物")
print("RG = Rạch, Giếng（ラック、ジエン）= 溝・小規模水路")
print("TH = Thủy Hệ（トゥイヘー）= 水系（河川・湖沼）")
print("TV = Thảm Thực Vật（タムトゥックバット）= 植生・土地利用")
print()
print("=" * 80)
