from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

from lib.followup_automation import process_pending_followups


def _load_env_file() -> None:
    if load_dotenv is None:
        return
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.is_file():
        return
    no_override = os.environ.get("LOAD_DOTENV_NO_OVERRIDE", "").strip() == "1"
    load_dotenv(env_file, override=not no_override)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    _load_env_file()

    parser = argparse.ArgumentParser(description="魂のナビ診断のメールキューを処理する worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="1回だけキューを処理して終了",
    )
    parser.add_argument(
        "--interval-sec",
        type=int,
        default=_int_env("FOLLOWUP_WORKER_INTERVAL_SEC", 30),
        help="常駐時のポーリング間隔（秒）",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=_int_env("FOLLOWUP_WORKER_MAX_ITEMS", 10),
        help="1回の処理で送る最大件数",
    )
    args = parser.parse_args()

    interval_sec = max(5, int(args.interval_sec))
    max_items = max(1, int(args.max_items))

    if args.once:
        sent = process_pending_followups(max_items=max_items)
        print(f"[{_timestamp()}] processed once: sent={sent}")
        return 0

    print(
        f"[{_timestamp()}] followup worker started "
        f"(interval={interval_sec}s, max_items={max_items})"
    )
    while True:
        try:
            sent = process_pending_followups(max_items=max_items)
            if sent:
                print(f"[{_timestamp()}] sent={sent}")
        except KeyboardInterrupt:
            print(f"[{_timestamp()}] followup worker stopped")
            return 0
        except Exception as exc:  # pragma: no cover
            print(f"[{_timestamp()}] worker error: {type(exc).__name__}: {exc}", file=sys.stderr)
        time.sleep(interval_sec)


if __name__ == "__main__":
    raise SystemExit(main())
