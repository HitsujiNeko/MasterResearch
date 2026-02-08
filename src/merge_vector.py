import argparse
import subprocess
from pathlib import Path


SUFFIXES = ["CS", "DC", "DH", "GT", "RG", "TH", "TV"]


def get_ogr2ogr_path() -> str:
	candidates = [
		r"C:\Program Files\QGIS 3.40.11\bin\ogr2ogr.exe",
		r"C:\OSGeo4W\bin\ogr2ogr.exe",
		r"C:\OSGeo4W64\bin\ogr2ogr.exe",
		"ogr2ogr",
	]
	for path in candidates:
		try:
			subprocess.run([path, "--version"], capture_output=True, text=True, check=True)
			return path
		except Exception:
			pass
	raise SystemExit("ogr2ogr が見つかりません。GDALのインストール確認が必要です。")


def merge_to_geopackage(input_dir: Path, suffix: str, output_root: Path, ogr2ogr_path: str):
	files = sorted(input_dir.glob("*.dgn"))
	if not files:
		print(f"No DGN files for {suffix} in {input_dir}")
		return

	out_gpkg = output_root / f"merge_{suffix}.gpkg"
	if out_gpkg.exists():
		out_gpkg.unlink()

	# Create target by copying first file's layers
	first = files[0]
	cmd_init = [
		ogr2ogr_path,
		"-f",
		"GPKG",
		str(out_gpkg),
		str(first),
	]
	subprocess.run(cmd_init, check=True)
	print(f"INIT: {first} -> {out_gpkg}")

	# Append the rest
	for f in files[1:]:
		cmd_append = [
			ogr2ogr_path,
			"-f",
			"GPKG",
			str(out_gpkg),
			str(f),
			"-update",
			"-append",
		]
		subprocess.run(cmd_append, check=True)
		print(f"APPEND: {f} -> {out_gpkg}")

	print(f"DONE: merge_{suffix}.gpkg created with {len(files)} inputs")


def main():
	parser = argparse.ArgumentParser(description="DGNを種類別にGeoPackageへ統合")
	parser.add_argument(
		"--root",
		type=Path,
		default=Path(r"c:\修士研究\整備データ"),
		help="Vector_* があるルートディレクトリ",
	)
	parser.add_argument(
		"--suffix",
		choices=SUFFIXES,
		help="特定種類のみ統合 (例: CS)",
	)
	args = parser.parse_args()

	ogr2ogr_path = get_ogr2ogr_path()
	print(f"Using ogr2ogr: {ogr2ogr_path}")

	targets = [args.suffix] if args.suffix else SUFFIXES
	for s in targets:
		in_dir = args.root / f"Vector_{s}"
		if not in_dir.exists():
			print(f"Missing directory: {in_dir}")
			continue
		merge_to_geopackage(in_dir, s, args.root, ogr2ogr_path)


if __name__ == "__main__":
	main()

