"""Run regression tests and validate tracked discovery reviews without crawling."""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    blocked = []

    def guard(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            blocked.append(event)
            raise RuntimeError("Network access is disabled during offline checks")

    # Applies to this process; spawned catalog-test workers only access local files.
    sys.addaudithook(guard)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1

    from pipeline.quality.discovery_review import report_review

    failures = []
    review_root = ROOT / "reviews" / "discovery"
    folders = sorted({path.parent for pattern in ("review.csv", "manifest.json")
                      for path in review_root.rglob(pattern)})
    for folder in folders:
        try:
            report = report_review(folder)
            print(f"{folder.relative_to(ROOT)}: {report['status']}; "
                  f"{report['unresolved_rows']}/{report['sample_rows']} unresolved")
        except (ValueError, OSError, KeyError, TypeError) as error:
            failures.append(folder)
            print(f"Invalid review bundle {folder.relative_to(ROOT)}: {error}", file=sys.stderr)
    if blocked:
        print(f"Offline checks attempted network access: {blocked}", file=sys.stderr)
    return int(bool(failures or blocked))


if __name__ == "__main__":
    raise SystemExit(main())
