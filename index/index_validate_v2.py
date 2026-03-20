#!/usr/bin/env python3

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ARCHIVE_EXTENSIONS = (".kpd", ".edat")
STATUS_OK = "ok"
STATUS_ISSUES = "issues"
STATUS_UNRESOLVED = "unresolved"


def clean_index_line(line: str) -> str:
    cleaned = line.strip()
    cleaned = cleaned.lstrip("✅❌").strip()
    return cleaned


def strip_archive_extension(part: str) -> str:
    lowered = part.lower()
    for ext in ARCHIVE_EXTENSIONS:
        if lowered.endswith(ext):
            return part[: -len(ext)]
    return part


def split_index_name(path: Path) -> tuple[str, ...]:
    return tuple(path.stem.split("__"))


def looks_like_folder_entry(name: str) -> bool:
    basename = Path(name.replace("\\", "/")).name
    return "." not in basename


def unique_tuples(values: Iterable[tuple[str, ...]]) -> list[tuple[str, ...]]:
    seen: set[tuple[str, ...]] = set()
    ordered: list[tuple[str, ...]] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def candidate_suffixes(parts: tuple[str, ...]) -> list[tuple[str, ...]]:
    stripped = tuple(strip_archive_extension(part) for part in parts)
    variants = (parts, stripped)
    candidates: list[tuple[str, ...]] = []
    for variant in variants:
        for start in range(len(variant)):
            candidates.append(variant[start:])
    return sorted(unique_tuples(candidates), key=lambda value: (-len(value), value))


@dataclass(frozen=True)
class IndexSpec:
    path: Path
    parts: tuple[str, ...]
    expected_names: set[str]
    skipped_folder_names: set[str]
    source_line_count: int

    @property
    def label(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class DirInfo:
    path: Path
    rel_parts: tuple[str, ...]
    child_names: set[str]

    @property
    def display_path(self) -> str:
        return "." if not self.rel_parts else "/".join(self.rel_parts)


@dataclass(frozen=True)
class ValidationResult:
    index_spec: IndexSpec
    matched_dir: DirInfo | None
    matched_by: str | None
    comparison_mode: str | None
    skipped_folder_entry_count: int
    missing_names: list[str]
    unexpected_names: list[str]
    status: str

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


def load_index_spec(path: Path, skip_folder_entries: bool = False) -> IndexSpec:
    lines = [clean_index_line(line) for line in path.read_text(encoding="utf-8").splitlines()]
    all_names = {line for line in lines if line}
    skipped_folder_names = {name for name in all_names if looks_like_folder_entry(name)} if skip_folder_entries else set()
    expected_names = all_names - skipped_folder_names
    return IndexSpec(
        path=path,
        parts=split_index_name(path),
        expected_names=expected_names,
        skipped_folder_names=skipped_folder_names,
        source_line_count=len([line for line in lines if line]),
    )


def discover_index_specs(index_root: Path, skip_folder_entries: bool = False) -> list[IndexSpec]:
    return [load_index_spec(path, skip_folder_entries=skip_folder_entries) for path in sorted(index_root.glob("*.txt"))]


def inventory_directories(export_root: Path) -> tuple[list[DirInfo], dict[str, list[DirInfo]]]:
    directories: list[DirInfo] = []
    by_last_part: dict[str, list[DirInfo]] = {}

    for current_root, dir_names, file_names in sorted(export_root.walk()):
        current_path = Path(current_root)
        rel_parts = () if current_path == export_root else current_path.relative_to(export_root).parts
        child_names = set(dir_names) | set(file_names)
        info = DirInfo(path=current_path, rel_parts=rel_parts, child_names=child_names)
        directories.append(info)
        if rel_parts:
            by_last_part.setdefault(rel_parts[-1], []).append(info)
    return directories, by_last_part


def score_dir_match(index_spec: IndexSpec, candidate: DirInfo, suffix: tuple[str, ...]) -> tuple[int, int, int, int, int]:
    overlap_count = len(index_spec.expected_names & candidate.child_names)
    missing_count = len(index_spec.expected_names - candidate.child_names)
    exact_match = int(candidate.child_names == index_spec.expected_names)
    return (
        exact_match,
        overlap_count,
        -missing_count,
        len(suffix),
        len(candidate.rel_parts),
    )


def match_directory(index_spec: IndexSpec, export_root_info: DirInfo, by_last_part: dict[str, list[DirInfo]]) -> tuple[DirInfo | None, str | None]:
    best_match: DirInfo | None = None
    best_mode: str | None = None
    best_score: tuple[int, int, int, int, int] | None = None

    for suffix in candidate_suffixes(index_spec.parts):
        for candidate in by_last_part.get(suffix[-1], []):
            if len(candidate.rel_parts) < len(suffix):
                continue
            if candidate.rel_parts[-len(suffix) :] != suffix:
                continue
            score = score_dir_match(index_spec, candidate, suffix)
            if best_score is None or score > best_score:
                best_match = candidate
                best_mode = f"path-suffix:{'/'.join(suffix)}"
                best_score = score

    if best_match is not None:
        return best_match, best_mode

    root_overlap = len(index_spec.expected_names & export_root_info.child_names)
    if root_overlap:
        return export_root_info, "export-root-overlap"

    return None, None


def validate_names(expected_names: set[str], actual_names: set[str]) -> tuple[list[str], list[str]]:
    missing_names = sorted(expected_names - actual_names)
    unexpected_names = sorted(actual_names - expected_names)
    return missing_names, unexpected_names


def collect_recursive_file_basenames(directory: Path) -> set[str]:
    return {path.name for path in directory.rglob("*") if path.is_file()}


def choose_actual_name_view(
    index_spec: IndexSpec,
    directory: Path,
    direct_names: set[str] | None = None,
    skip_folder_entries: bool = False,
) -> tuple[set[str], str]:
    direct_names = {entry.name for entry in directory.iterdir()} if direct_names is None else direct_names
    recursive_names = collect_recursive_file_basenames(directory)
    if skip_folder_entries:
        direct_file_names = {entry.name for entry in directory.iterdir() if entry.is_file()}
        candidates = [
            ("direct-files-only", direct_file_names),
            ("recursive-file-basenames", recursive_names),
        ]
    else:
        candidates = [
            ("direct-children", direct_names),
            ("recursive-file-basenames", recursive_names),
        ]

    best_mode = "direct-children" if not skip_folder_entries else "direct-files-only"
    best_names = direct_names if not skip_folder_entries else {entry.name for entry in directory.iterdir() if entry.is_file()}
    best_score: tuple[int, int, int, int] | None = None

    for mode, names in candidates:
        missing_names, unexpected_names = validate_names(index_spec.expected_names, names)
        prefer_direct = 1 if mode == "direct-children" else 0
        score = (
            -len(missing_names),
            -len(unexpected_names),
            int(names == index_spec.expected_names),
            prefer_direct,
        )
        if best_score is None or score > best_score:
            best_mode = mode
            best_names = names
            best_score = score

    return best_names, best_mode


def validate_single_directory(index_spec: IndexSpec, directory: Path) -> ValidationResult:
    child_names = {entry.name for entry in directory.iterdir()}
    matched_dir = DirInfo(path=directory, rel_parts=directory.parts, child_names=child_names)
    actual_names, comparison_mode = choose_actual_name_view(
        index_spec,
        directory,
        direct_names=child_names,
        skip_folder_entries=bool(index_spec.skipped_folder_names),
    )
    missing_names, unexpected_names = validate_names(index_spec.expected_names, actual_names)
    status = STATUS_OK if not missing_names and not unexpected_names else STATUS_ISSUES
    return ValidationResult(
        index_spec=index_spec,
        matched_dir=matched_dir,
        matched_by="manual",
        comparison_mode=comparison_mode,
        skipped_folder_entry_count=len(index_spec.skipped_folder_names),
        missing_names=missing_names,
        unexpected_names=unexpected_names,
        status=status,
    )


def validate_tree(index_specs: list[IndexSpec], export_root: Path) -> list[ValidationResult]:
    directories, by_last_part = inventory_directories(export_root)
    export_root_info = next(info for info in directories if info.path == export_root)
    results: list[ValidationResult] = []

    for index_spec in index_specs:
        matched_dir, matched_by = match_directory(index_spec, export_root_info, by_last_part)
        if matched_dir is None:
            results.append(
                ValidationResult(
                    index_spec=index_spec,
                    matched_dir=None,
                    matched_by=None,
                    comparison_mode=None,
                    skipped_folder_entry_count=len(index_spec.skipped_folder_names),
                    missing_names=sorted(index_spec.expected_names),
                    unexpected_names=[],
                    status=STATUS_UNRESOLVED,
                )
            )
            continue

        actual_names, comparison_mode = choose_actual_name_view(
            index_spec,
            matched_dir.path,
            direct_names=matched_dir.child_names,
            skip_folder_entries=bool(index_spec.skipped_folder_names),
        )
        missing_names, unexpected_names = validate_names(index_spec.expected_names, actual_names)
        status = STATUS_OK if not missing_names and not unexpected_names else STATUS_ISSUES
        results.append(
            ValidationResult(
                index_spec=index_spec,
                matched_dir=matched_dir,
                matched_by=matched_by,
                comparison_mode=comparison_mode,
                skipped_folder_entry_count=len(index_spec.skipped_folder_names),
                missing_names=missing_names,
                unexpected_names=unexpected_names,
                status=status,
            )
        )
    return results


def result_to_dict(result: ValidationResult) -> dict[str, object]:
    return {
        "index_file": str(result.index_spec.path),
        "matched_dir": None if result.matched_dir is None else str(result.matched_dir.path),
        "matched_by": result.matched_by,
        "comparison_mode": result.comparison_mode,
        "expected_count": len(result.index_spec.expected_names),
        "skipped_folder_entry_count": result.skipped_folder_entry_count,
        "skipped_folder_names": sorted(result.index_spec.skipped_folder_names),
        "missing_count": len(result.missing_names),
        "unexpected_count": len(result.unexpected_names),
        "missing_names": result.missing_names,
        "unexpected_names": result.unexpected_names,
        "status": result.status,
    }


def print_result(result: ValidationResult, verbose: bool, show_ok: bool) -> None:
    if result.ok and not show_ok:
        return

    matched = "(unresolved)" if result.matched_dir is None else result.matched_dir.display_path
    print(
        f"[{result.status.upper()}] {result.index_spec.label} -> {matched}"
        f" | missing={len(result.missing_names)} unexpected={len(result.unexpected_names)}"
    )
    if result.matched_by:
        print(f"  matched_by: {result.matched_by}")
    if result.comparison_mode:
        print(f"  compare_as: {result.comparison_mode}")
    if result.skipped_folder_entry_count:
        print(f"  skipped_folder_entries: {result.skipped_folder_entry_count}")

    names_to_show: list[tuple[str, list[str]]] = []
    if result.missing_names:
        names_to_show.append(("missing", result.missing_names))
    if result.unexpected_names:
        names_to_show.append(("unexpected", result.unexpected_names))

    if verbose:
        limit = None
    else:
        limit = 10

    for label, names in names_to_show:
        shown = names if limit is None else names[:limit]
        for name in shown:
            print(f"  {label}: {name}")
        if limit is not None and len(names) > limit:
            print(f"  {label}: ... {len(names) - limit} more")


def print_summary(results: list[ValidationResult], strict_unexpected: bool, skip_folder_entries: bool) -> None:
    unresolved = sum(1 for result in results if result.status == STATUS_UNRESOLVED)
    with_missing = sum(1 for result in results if result.missing_names)
    with_unexpected = sum(1 for result in results if result.unexpected_names)
    ok = sum(1 for result in results if result.ok)
    print(
        f"Summary: ok={ok} issues={len(results) - ok} unresolved={unresolved} "
        f"indices={len(results)} missing_sets={with_missing} unexpected_sets={with_unexpected}"
    )
    if strict_unexpected:
        print("Strict unexpected mode: unexpected names count as validation failures.")
    else:
        print("Default mode: unexpected names are reported, but only missing/unresolved sets fail the exit code.")
    if skip_folder_entries:
        print("Folder-skip mode: index lines without a dot are ignored as folder-style entries.")


def exit_code_for_results(results: list[ValidationResult], strict_unexpected: bool) -> int:
    for result in results:
        if result.status == STATUS_UNRESOLVED or result.missing_names:
            return 1
        if strict_unexpected and result.unexpected_names:
            return 1
    return 0


def resolve_index_path(index_arg: str, index_root: Path) -> Path:
    candidate = Path(index_arg)
    if candidate.exists():
        return candidate
    fallback = index_root / index_arg
    if fallback.exists():
        return fallback
    raise FileNotFoundError(index_arg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate extracted output against cleaned KPD index list files."
    )
    parser.add_argument(
        "export_path",
        help="Extracted output directory. For single-index mode this is the specific extracted folder.",
    )
    parser.add_argument(
        "--index-root",
        default="Index/List",
        help="Directory that contains the cleaned index .txt files. Default: Index/List",
    )
    parser.add_argument(
        "--index",
        help="Validate one specific index file against export_path instead of scanning the whole index directory.",
    )
    parser.add_argument(
        "--json-out",
        help="Optional path for a JSON report.",
    )
    parser.add_argument(
        "--strict-unexpected",
        action="store_true",
        help="Treat unexpected names as a validation failure in the exit code.",
    )
    parser.add_argument(
        "--skip-folder-entries",
        action="store_true",
        help="Ignore folder-style index entries (lines without a dot) so flattened exports compare more like older extraction layouts.",
    )
    parser.add_argument(
        "--show-ok",
        action="store_true",
        help="Print successful matches as well as failures.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print all missing/unexpected names instead of truncating to the first 10 per set.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    export_path = Path(args.export_path)
    index_root = Path(args.index_root)

    if not export_path.is_dir():
        print(f"Export path is not a directory: {export_path}", file=sys.stderr)
        return 2
    if not index_root.is_dir():
        print(f"Index root is not a directory: {index_root}", file=sys.stderr)
        return 2

    if args.index:
        index_path = resolve_index_path(args.index, index_root)
        index_specs = [load_index_spec(index_path, skip_folder_entries=args.skip_folder_entries)]
        results = [validate_single_directory(index_specs[0], export_path)]
    else:
        index_specs = discover_index_specs(index_root, skip_folder_entries=args.skip_folder_entries)
        results = validate_tree(index_specs, export_path)

    for result in results:
        print_result(result, verbose=args.verbose, show_ok=args.show_ok)
    print_summary(
        results,
        strict_unexpected=args.strict_unexpected,
        skip_folder_entries=args.skip_folder_entries,
    )

    if args.json_out:
        payload = {
            "tool": "index_validate_v2.py",
            "export_path": str(export_path),
            "index_root": str(index_root),
            "single_index": args.index is not None,
            "strict_unexpected": args.strict_unexpected,
            "skip_folder_entries": args.skip_folder_entries,
            "summary": {
                "index_count": len(results),
                "ok_count": sum(1 for result in results if result.ok),
                "issue_count": sum(1 for result in results if not result.ok),
                "unresolved_count": sum(1 for result in results if result.status == STATUS_UNRESOLVED),
            },
            "results": [result_to_dict(result) for result in results],
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return exit_code_for_results(results, strict_unexpected=args.strict_unexpected)


if __name__ == "__main__":
    raise SystemExit(main())
