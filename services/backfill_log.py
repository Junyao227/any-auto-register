"""CPA / 集成补传流程的控制台日志（输出到 API 进程 stdout）。"""

from __future__ import annotations

from datetime import datetime


def backfill_log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [CPA补传] {msg}", flush=True)


def mask_secret(value: str | None, *, visible: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "(未配置)"
    if len(text) <= visible * 2:
        return "*" * len(text)
    return f"{text[:visible]}...{text[-visible:]}"
