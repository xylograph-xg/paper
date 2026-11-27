import json
from core.api import paths__WorkspacePath as Path
import subprocess
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from core import services


class BridgeProgress(unittest.TestCase):
    def test_progress_is_readable_before_child_completes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);log=root/'progress.log';gate=root/'release'
            (root/'fixture_bridge.py').write_text(
                "import json,sys,time\nfrom pathlib import Path\n"
                "data=json.load(sys.stdin)\nprint('stage started',file=sys.stderr,flush=True)\n"
                "while not Path(data['gate']).exists():time.sleep(.01)\n"
                "print(json.dumps({'complete':True}))\n")
            with patch.object(services,'ROOT',root),ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(services.bridge,'fixture_bridge',{'gate':str(gate)},log,5)
                try:
                    deadline=time.monotonic()+3
                    while time.monotonic()<deadline:
                        if log.exists() and 'stage started' in log.read_text():break
                        time.sleep(.01)
                    self.assertIn('stage started',log.read_text())
                    self.assertFalse(future.done())
                finally:gate.touch()
                self.assertEqual(future.result(timeout=5),{'complete':True})

    def test_timeout_preserves_live_stderr_and_partial_stdout(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);log=root/'progress.log'
            (root/'fixture_bridge.py').write_text(
                "import sys,time\nprint('last stage',file=sys.stderr,flush=True)\n"
                "print('partial result',flush=True)\ntime.sleep(10)\n")
            with patch.object(services,'ROOT',root),self.assertRaises(subprocess.TimeoutExpired):
                services.bridge('fixture_bridge',{},log,.3)
            self.assertIn('last stage',log.read_text())
            self.assertIn('partial result',Path(str(log)+'.stdout').read_text())

    def test_failure_keeps_error_in_log_and_exception(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);log=root/'progress.log'
            (root/'fixture_bridge.py').write_text("import sys\nprint('specific failure',file=sys.stderr,flush=True)\nsys.exit(2)\n")
            with patch.object(services,'ROOT',root),self.assertRaisesRegex(RuntimeError,'specific failure'):
                services.bridge('fixture_bridge',{},log,3)
            self.assertIn('specific failure',log.read_text())
