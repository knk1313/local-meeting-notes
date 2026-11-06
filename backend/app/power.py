"""処理中にMacが放置で勝手にスリープしないようにする処理。"""

from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import contextmanager
from typing import Iterator


#: macOS に付属する、スリープを抑止するコマンド。
CAFFEINATE = "caffeinate"


@contextmanager
def prevent_idle_sleep() -> Iterator[None]:
    """ブロックの間、操作が無くてもシステムがスリープしないようにする。

    文字起こしは数分以上かかり、途中でスリープすると通信が切れるため。
    ふたを閉じたときのスリープは防げない（そちらは送り直しで拾う）。
    ``caffeinate`` が無い環境や起動に失敗した場合は、何もせずに処理を続ける。
    """
    process = _start_caffeinate()
    try:
        yield
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def _start_caffeinate() -> subprocess.Popen[bytes] | None:
    """``caffeinate`` を起動する。使えない場合はNone。"""
    command = shutil.which(CAFFEINATE)
    if command is None:
        return None
    try:
        # -w: このプロセスが異常終了しても、caffeinate が残り続けないようにする。
        return subprocess.Popen(
            [command, "-i", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
