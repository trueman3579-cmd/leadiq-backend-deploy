"""
backend/__main__.py — CLI entry point for the LeadIQ engine.
Usage: python -m backend --cmd run-pipeline | benchmark
"""
import asyncio
import argparse
import logging
import sys

from backend.pipeline_v3 import run_full_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("leadiq")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LeadIQ v3 — World-class lead intelligence")
    parser.add_argument("--cmd", default="run-pipeline", help="Command to run")
    parser.add_argument("--limit", type=int, default=50, help="Max leads to return")
    args = parser.parse_args(argv)

    if args.cmd == "run-pipeline":
        leads = asyncio.run(run_full_pipeline())
        print(f"\n🏆 Pipeline complete: {len(leads)} leads scored")
        hot = [l for l in leads if l.confidence == "HOT"]
        warm = [l for l in leads if l.confidence == "WARM"]
        cool = [l for l in leads if l.confidence == "COOL"]
        print(f"   HOT: {len(hot)}  WARM: {len(warm)}  COOL: {len(cool)}  COLD: {len(leads) - len(hot) - len(warm) - len(cool)}")
        return 0
    elif args.cmd == "benchmark":
        print("Running benchmark against commercial platforms...")
        # TODO: implement full benchmark
        return 0
    else:
        print(f"Unknown command: {args.cmd}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
