import argparse
import shutil
from pathlib import Path


SUFFIXES = ["CS", "DC", "DH", "GT", "RG", "TH", "TV"]


def find_dgn_files(source_root: Path):
	for region_dir in sorted(source_root.glob("*/")):
		if not region_dir.is_dir():
			continue
		for suffix in SUFFIXES:
			pattern = f"*_{suffix}.dgn"
			for f in region_dir.glob(pattern):
				yield suffix, f


def ensure_targets(target_root: Path):
	targets = {}
	for suffix in SUFFIXES:
		t = target_root / f"Vector_{suffix}"
		t.mkdir(parents=True, exist_ok=True)
		targets[suffix] = t
	return targets


def copy_files(source_root: Path, target_root: Path, dry_run: bool, overwrite: bool, only_suffix: str | None):
	targets = ensure_targets(target_root)
	total = 0
	copied = 0
	skipped = 0

	for suffix, src in find_dgn_files(source_root):
		if only_suffix and suffix != only_suffix:
			continue
		total += 1
		dst_dir = targets[suffix]
		dst = dst_dir / src.name

		if dst.exists() and not overwrite:
			skipped += 1
			print(f"SKIP exists: {dst}")
			continue

		if dry_run:
			copied += 1
			action = "WOULD COPY (overwrite)" if dst.exists() else "WOULD COPY"
			print(f"{action}: {src} -> {dst}")
		else:
			shutil.copy2(src, dst)
			copied += 1
			print(f"COPIED: {src} -> {dst}")

	print(f"\nSummary: total_found={total}, copied={copied}, skipped={skipped}")


def main():
	parser = argparse.ArgumentParser(description="DGNファイルを種類別にディレクトリへコピー")
	parser.add_argument(
		"--source",
		type=Path,
		default=Path(r"c:\修士研究\SSD\ベクタ\NhomTL_BanDo"),
		help="領域フォルダが並ぶソースのルート",
	)
	parser.add_argument(
		"--target",
		type=Path,
		default=Path(r"c:\修士研究\整備データ"),
		help="Vector_* を作成するターゲットのルート",
	)
	parser.add_argument(
		"--dry-run",
		action="store_true",
		help="コピーせずに予定のみ表示",
	)
	parser.add_argument(
		"--overwrite",
		action="store_true",
		help="同名ファイルがある場合に上書き",
	)
	parser.add_argument(
		"--suffix",
		choices=SUFFIXES,
		help="特定種類のみ処理 (例: CS)",
	)
	args = parser.parse_args()

	if not args.source.exists():
		raise SystemExit(f"ソースが存在しません: {args.source}")

	copy_files(args.source, args.target, args.dry_run, args.overwrite, args.suffix)


if __name__ == "__main__":
	main()

