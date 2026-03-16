"""
LSTデータの詳細分析スクリプト
目的：LST算出結果のCRS、解像度、空間範囲を把握する
"""
import pandas as pd
import geopandas as gpd
from pathlib import Path
import json
import warnings
warnings.filterwarnings('ignore')

def analyze_lst_config():
    """LST算出設定ファイルの分析"""
    config_path = Path("data/input/gee_calc_LST_info.csv")
    
    print("=" * 80)
    print("LST算出設定の分析")
    print("=" * 80)
    
    if not config_path.exists():
        print(f"警告: {config_path} が見つかりません")
        return None
    
    try:
        df = pd.read_csv(config_path)
        print(f"\n設定ファイル: {config_path}")
        print(f"設定数: {len(df)}")
        
        print("\n設定内容:")
        for idx, row in df.iterrows():
            print(f"\n  設定 {idx + 1}:")
            for col in df.columns:
                print(f"    {col}: {row[col]}")
        
        return df.to_dict('records')
        
    except Exception as e:
        print(f"エラー: {e}")
        return None


def analyze_lst_results():
    """LST算出結果CSVの分析"""
    results_path = Path("data/output/gee_calc_LST_results.csv")
    
    print("\n" + "=" * 80)
    print("LST算出結果の分析")
    print("=" * 80)
    
    if not results_path.exists():
        print(f"警告: {results_path} が見つかりません")
        return None
    
    try:
        df = pd.read_csv(results_path)
        print(f"\n結果ファイル: {results_path}")
        print(f"レコード数: {len(df)}")
        
        # 基本統計
        print(f"\n基本統計:")
        print(f"  対象日数: {len(df)}")
        print(f"  衛星種別: {df['satellite'].unique().tolist()}")
        print(f"  期間: {df['date'].min()} ～ {df['date'].max()}")
        
        # エクスポート済みデータ
        exported = df[df['exported'] == True]
        print(f"\n  エクスポート済み: {len(exported)}/{len(df)} ({len(exported)/len(df)*100:.1f}%)")
        
        # 有効ピクセル率の統計
        print(f"\n有効ピクセル率:")
        print(f"  平均: {df['valid_pixel_ratio'].mean():.2f}%")
        print(f"  最小: {df['valid_pixel_ratio'].min():.2f}%")
        print(f"  最大: {df['valid_pixel_ratio'].max():.2f}%")
        
        # LST統計（有効なデータのみ）
        valid_data = df[df['valid_pixel_ratio'] > 50]
        if len(valid_data) > 0:
            print(f"\nLST統計（有効ピクセル率>50%のデータ）:")
            print(f"  対象日数: {len(valid_data)}")
            print(f"  平均気温: {valid_data['mean_temp_c'].mean():.2f}°C")
            print(f"  最低気温: {valid_data['min_temp_c'].min():.2f}°C")
            print(f"  最高気温: {valid_data['max_temp_c'].max():.2f}°C")
        
        return df.to_dict('records')
        
    except Exception as e:
        print(f"エラー: {e}")
        return None


def analyze_lst_roi():
    """LST算出対象エリア（ROI）の分析"""
    roi_dir = Path("data/GISData/ROI")
    
    print("\n" + "=" * 80)
    print("ROI（対象エリア）の分析")
    print("=" * 80)
    
    if not roi_dir.exists():
        print(f"警告: {roi_dir} が見つかりません")
        return None
    
    roi_files = list(roi_dir.glob("*.shp")) + list(roi_dir.glob("*.gpkg")) + list(roi_dir.glob("*.geojson"))
    
    print(f"\nROIディレクトリ: {roi_dir}")
    print(f"ROIファイル数: {len(roi_files)}")
    
    roi_info = {}
    
    for roi_file in roi_files:
        try:
            print(f"\n--- {roi_file.name} ---")
            gdf = gpd.read_file(roi_file)
            
            print(f"  CRS: {gdf.crs}")
            if gdf.crs:
                print(f"  EPSG: {gdf.crs.to_epsg()}")
            
            print(f"  ジオメトリ数: {len(gdf)}")
            print(f"  ジオメトリタイプ: {gdf.geometry.geom_type.unique().tolist()}")
            
            # 空間範囲
            bounds = gdf.total_bounds
            print(f"  空間範囲（元の座標系）:")
            print(f"    X: {bounds[0]:.6f} ～ {bounds[2]:.6f}")
            print(f"    Y: {bounds[1]:.6f} ～ {bounds[3]:.6f}")
            
            # WGS84に変換
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf_wgs84 = gdf.to_crs(epsg=4326)
                bounds_wgs84 = gdf_wgs84.total_bounds
                print(f"  空間範囲（WGS84 - 経度緯度）:")
                print(f"    経度: {bounds_wgs84[0]:.6f} ～ {bounds_wgs84[2]:.6f}")
                print(f"    緯度: {bounds_wgs84[1]:.6f} ～ {bounds_wgs84[3]:.6f}")
                
                roi_info[roi_file.stem] = {
                    'file': roi_file.name,
                    'crs': str(gdf.crs),
                    'epsg': gdf.crs.to_epsg(),
                    'feature_count': len(gdf),
                    'bounds_wgs84': {
                        'lon_min': float(bounds_wgs84[0]),
                        'lat_min': float(bounds_wgs84[1]),
                        'lon_max': float(bounds_wgs84[2]),
                        'lat_max': float(bounds_wgs84[3])
                    }
                }
            else:
                roi_info[roi_file.stem] = {
                    'file': roi_file.name,
                    'crs': str(gdf.crs),
                    'epsg': gdf.crs.to_epsg() if gdf.crs else None,
                    'feature_count': len(gdf),
                    'bounds_wgs84': {
                        'lon_min': float(bounds[0]),
                        'lat_min': float(bounds[1]),
                        'lon_max': float(bounds[2]),
                        'lat_max': float(bounds[3])
                    }
                }
            
            # 属性カラム
            if len(gdf.columns) > 1:  # geometry以外
                print(f"  属性カラム:")
                for col in gdf.columns:
                    if col != 'geometry':
                        print(f"    - {col}: {gdf[col].dtype}")
        
        except Exception as e:
            print(f"  エラー: {e}")
    
    return roi_info


def main():
    """メイン処理"""
    print("=" * 80)
    print("LSTデータ詳細分析")
    print("=" * 80)
    
    result = {
        'config': None,
        'results': None,
        'roi': None
    }
    
    # 1. 設定ファイル分析
    config = analyze_lst_config()
    result['config'] = config
    
    # 2. 結果ファイル分析
    results = analyze_lst_results()
    result['results'] = results
    
    # 3. ROI分析
    roi = analyze_lst_roi()
    result['roi'] = roi
    
    # 結果をJSONで保存
    output_file = Path("data/output/lst_data_analysis.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*80}")
    print(f"分析完了！結果を {output_file} に保存しました")
    print('='*80)
    
    # サマリー
    print("\n【サマリー】")
    if config:
        print(f"LST算出設定: {len(config)}件")
    if results:
        print(f"LST算出結果: {len(results)}レコード")
    if roi:
        print(f"ROIファイル: {len(roi)}件")
        for name, info in roi.items():
            print(f"  - {name}: EPSG:{info['epsg']}, {info['feature_count']}地物")


if __name__ == "__main__":
    main()
