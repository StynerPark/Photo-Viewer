import os
import sys
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
exit_code = 0 if result.wasSuccessful() else 1

# The tests intentionally exercise delayed Qt/VLC cleanup workers. All test
# assertions and cleanup hooks have completed at this point; avoid waiting for
# PySide's process-global teardown during non-interactive CI shutdown.
sys.stdout.flush()
sys.stderr.flush()
os._exit(exit_code)
