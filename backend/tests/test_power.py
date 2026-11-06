"""スリープ抑止のユニットテスト。"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from app.power import prevent_idle_sleep


class PreventIdleSleepTest(unittest.TestCase):
    """処理の間だけ caffeinate を動かす。"""

    @patch("app.power.shutil.which", return_value="/usr/bin/caffeinate")
    @patch("app.power.subprocess.Popen")
    def test_runs_caffeinate_only_while_processing(self, popen: MagicMock, _which: MagicMock) -> None:
        """ブロックに入ると起動し、抜けると止める。"""
        with prevent_idle_sleep():
            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0], ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
            popen.return_value.terminate.assert_not_called()

        popen.return_value.terminate.assert_called_once()

    @patch("app.power.shutil.which", return_value="/usr/bin/caffeinate")
    @patch("app.power.subprocess.Popen")
    def test_stops_caffeinate_when_processing_fails(self, popen: MagicMock, _which: MagicMock) -> None:
        """処理が例外で終わっても止める。"""
        with self.assertRaises(RuntimeError):
            with prevent_idle_sleep():
                raise RuntimeError("失敗")

        popen.return_value.terminate.assert_called_once()

    @patch("app.power.shutil.which", return_value=None)
    @patch("app.power.subprocess.Popen")
    def test_does_nothing_without_caffeinate(self, popen: MagicMock, _which: MagicMock) -> None:
        """caffeinate が無い環境では、何もせずに処理を続ける。"""
        with prevent_idle_sleep():
            pass

        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
