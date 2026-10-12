"""Partition the complete unittest discovery result across independent runners."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import unittest


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--list", action="store_true", help="Print selected test IDs without executing them.")
    args = parser.parse_args()
    if args.shards < 1 or not 0 <= args.shard < args.shards:
        parser.error("require 0 <= shard < shards")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "python-core" / "src"))
    suite = unittest.defaultTestLoader.discover(str(root / "python-core" / "tests"))
    if unittest.defaultTestLoader.errors:
        for error in unittest.defaultTestLoader.errors:
            print(error, file=sys.stderr)
        return 1
    discovered = list(cases(suite))
    selected = discovered[args.shard::args.shards]
    if not selected:
        print("No tests selected; refusing an empty successful shard.", file=sys.stderr)
        return 1
    print(f"Shard {args.shard + 1}/{args.shards}: {len(selected)} of {len(discovered)} discovered tests", flush=True)
    if args.list:
        for test in selected:
            print(test.id())
        return 0
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
