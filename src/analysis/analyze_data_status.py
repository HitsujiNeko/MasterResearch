"""
GISデータとLSTデータの詳細分析スクリプト（統合版）
目的：データ整備状況記録に必要な情報を収集
"""
import geopandas as gpd
import pandas as pd
import fiona
from pathlib import Path
import json
import warnings
warnings.filterwarnings('ignore')


def analyze_gis_data():
    """GISデータ（gpkg）の分析"""
    merge_dir = Path("整備データ/merge")
    suffixes = ["CS", "DC", "DH", "GT", "RG", "TH", "TV"]
    
    print("=" * 80)
    print("GISデータ分析")
    print("=" * 80)
    
    gis_results = {}
    
    for suffix in suffixes:
        gpkg_file = merge_dir / f"merge_{suffix}.gpkg"
        if not gpkg_file.exists():
            continue
        
        print(f"\n【{suffix}】 {gpkg_file.name}")
        
        try:
            # ファイル情報
            file_size_mb = gpkg_file.stat().st_size / (1024 * 1024)
            print(f"  サイズ: {file_size_mb:.2f} MB")
            
            # データ読込（geometryのみ、テキスト属性はスキップ）
            try:
                gdf = gpd.read_file(str(gpkg_file), encoding='utf-8', ignore_geometry=False)
            except UnicodeDecodeError:
                # エンコーディングエラー時は、latin1で試行
                try:
                    gdf = gpd.read_file(str(gpkg_file), encoding='latin1')
                except:
                    # 最終手段：fionaで直接読み込み、geometryのみ取得
                    import fiona
                    features = []
                    with fiona.open(str(gpkg_file)) as src:
                        for feat in src:
                            features.append(feat)
                    gdf = gpd.GeoDataFrame.from_features(features)
            
            # CRS情報
            crs_str = str(gdf.crs) if gdf.crs else "未定義"
            crs_epsg = gdf.crs.to_epsg() if gdf.crs else None
            
            print(f"  CRS: {crs_str[:60]}")
            if crs_epsg:
                print(f"  EPSG: {crs_epsg}")
            else:
                print(f"  EPSG: 未定義（ローカル座標系の可能性）")
            
            # 地物数
            print(f"  地物数: {len(gdf):,}")
            
            # ジオメトリタイプ
            geom_types = gdf.geometry.geom_type.value_counts()
            print(f"  ジオメト リタイプ:")
            for gt, count in geom_types.items():
                print(f"    - {gt}: {count:,}")
            
            # 空間範囲
            bounds = gdf.total_bounds
            print(f"  空間範囲（投影座標）:")
            print(f"    X: {bounds[0]:.2f} ～ {bounds[2]:.2f}")
            print(f"    Y: {bounds[1]:.2f} ～ {bounds[3]:.2f}")
            
            # WGS84への変換を試行
            bounds_wgs84 = None
            crs_assumed = None
            if crs_epsg:
                if crs_epsg != 4326:
                    try:
                        gdf_wgs84 = gdf.to_crs(epsg=4326)
                        bounds_wgs84 = gdf_wgs84.total_bounds
                        print(f"  空間範囲（WGS84）:")
                        print(f"    経度: {bounds_wgs84[0]:.6f} ～ {bounds_wgs84[2]:.6f}")
                        print(f"    緯度: {bounds_wgs84[1]:.6f} ～ {bounds_wgs84[3]:.6f}")
                    except:
                        pass
            else:
                # CRS未定義の場合、座標範囲からVN-2000 (EPSG:3405)と推定して変換
                if 400000 < bounds[0] < 800000 and 1500000 < bounds[1] <2500000:
                    try:
                        print(f"  → 座標範囲からEPSG:3405 (VN-2000)と推定")
                        gdf_assumed = gdf.set_crs(epsg=3405, allow_override=True)
                        gdf_wgs84 = gdf_assumed.to_crs(epsg=4326)
                        bounds_wgs84 = gdf_wgs84.total_bounds
                        print(f"  空間範囲（WGS84・推定）:")
                        print(f"    経度: {bounds_wgs84[0]:.6f} ～ {bounds_wgs84[2]:.6f}")
                        print(f"    緯度: {bounds_wgs84[1]:.6f} ～ {bounds_wgs84[3]:.6f}")
                        crs_assumed = "EPSG:3405"
                    except Exception as e:
                        print(f"  WGS84変換失敗: {e}")
            
            # 結果保存
            gis_results[suffix] = {
                'file': gpkg_file.name,
                'file_size_mb': round(file_size_mb, 2),
                'crs': crs_str,
                'crs_epsg': crs_epsg,
                'crs_assumed': crs_assumed,
                'feature_count': len(gdf),
                'geometry_types': geom_types.to_dict(),
                'bounds': {
                    'minx': float(bounds[0]),
                    'miny': float(bounds[1]),
                    'maxx': float(bounds[2]),
                    'maxy': float(bounds[3])
                }
            }
            
            if bounds_wgs84 is not None:
                gis_results[suffix]['bounds_wgs84'] = {
                    'lon_min': float(bounds_wgs84[0]),
                    'lat_min': float(bounds_wgs84[1]),
                    'lon_max': float(bounds_wgs84[2]),
                    'lat_max': float(bounds_wgs84[3])
                }
            
        except Exception as e:
            print(f"  エラー: {e}")
            gis_results[suffix] = {'error': str(e)}
    
    return gis_results


def analyze_lst_data():
    """LSTデータの分析"""
    print("\n" + "=" * 80)
    print("LSTデータ分析")
    print("=" * 80)
    
    lst_results = {}
    
    # 1. 設定ファイル
    config_path = Path("data/input/gee_calc_LST_info.csv")
    if config_path.exists():
        df_config = pd.read_csv(config_path)
        print(f"\n設定ファイル: {config_path}")
        print(f"設定数: {len(df_config)}")
        for idx, row in df_config.iterrows():
            print(f"\n  設定 {idx+1}:")
            print(f"    ROI: {row['roi_shapefile_path']}")
            print(f"    期間: {row['start_date']} ～ {row['end_date']}")
            print(f"    出力EPSG: {row['output_epsg']}")
            print(f"    手法: {row['lst_method']}")
        
        lst_results['config'] = df_config.to_dict('records')
    
    # 2. 結果ファイル
    results_path = Path("data/output/gee_calc_LST_results.csv")
    if results_path.exists():
        df_results = pd.read_csv(results_path)
        print(f"\n結果ファイル: {results_path}")
        print(f"レコード数: {len(df_results)}")
        print(f"期間: {df_results['date'].min()} ～ {df_results['date'].max()}")
        
        exported = df_results[df_results['exported'] == True]
        print(f"エクスポート済み: {len(exported)}/{len(df_results)}")
        
        valid = df_results[df_results['valid_pixel_ratio'] > 50]
        if len(valid) > 0:
            print(f"\n有効データ（有効ピクセル>50%）: {len(valid)}件")
            print(f"  平均LST: {valid['mean_temp_c'].mean():.2f}°C")
            print(f"  LST範囲: {valid['min_temp_c'].min():.2f} ～ {valid['max_temp_c'].max():.2f}°C")
        
        lst_results['results_summary'] = {
            'record_count': len(df_results),
            'exported_count': len(exported),
            'valid_count': len(valid)
        }
    
    # 3. ROIファイル
    roi_dir = Path("data/GISData/ROI")
    if roi_dir.exists():
        roi_files = list(roi_dir.rglob("*.shp")) + list(roi_dir.rglob("*.gpkg"))
        print(f"\nROIファイル: {len(roi_files)}件")
        
        roi_info = {}
        for roi_file in roi_files:
            try:
                gdf = gpd.read_file(roi_file)
                bounds_wgs84 = gdf.to_crs(epsg=4326).total_bounds
                
                print(f"\n  {roi_file.name}:")
                print(f"    CRS: EPSG:{gdf.crs.to_epsg()}")
                print(f"    範囲（WGS84）: 経度 {bounds_wgs84[0]:.4f}～{bounds_wgs84[2]:.4f}, "
                      f"緯度 {bounds_wgs84[1]:.4f}～{bounds_wgs84[3]:.4f}")
                
                roi_info[roi_file.stem] = {
                    'file': roi_file.name,
                    'crs_epsg': gdf.crs.to_epsg(),
                    'bounds_wgs84': {
                        'lon_min': float(bounds_wgs84[0]),
                        'lat_min': float(bounds_wgs84[1]),
                        'lon_max': float(bounds_wgs84[2]),
                        'lat_max': float(bounds_wgs84[3])
                    }
                }
            except Exception as e:
                print(f"  {roi_file.name}: エラー - {e}")
        
        lst_results['roi'] = roi_info
    
    return lst_results


def main():
    """メイン処理"""
    print("データ整備状況分析")
    print()
    
    # GISデータ分析
    gis_results = analyze_gis_data()
    
    # LSTデータ分析
    lst_results = analyze_lst_data()
    
    # 結果を保存
    output_file = Path("data/output/data_preparation_analysis.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    combined = {
        'gis_data': gis_results,
        'lst_data': lst_results
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*80}")
    print(f"分析完了！結果を {output_file} に保存しました")
    print('='*80)


if __name__ == "__main__":
    main()
