import subprocess
import sys
import threading
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
command = [
    sys.executable,
    "-u",
    "-m",
    "unittest",
    "discover",
    "-s",
    str(root / "tests"),
    "-p",
    "test_*.py",
    "-v",
]

process = subprocess.Popen(
    command,
    cwd=root,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
)
success_reported = threading.Event()


def forward_output():
    assert process.stdout is not None
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        if line.strip() == "OK":
            success_reported.set()


reader = threading.Thread(target=forward_output, daemon=True)
reader.start()
deadline = time.monotonic() + 600

while process.poll() is None:
    if success_reported.wait(0.25):
        # unittest only prints the final uppercase OK after every assertion and
        # cleanup hook has completed. Qt/VLC can still keep a Windows process
        # alive during global teardown, so give it a moment and then end only
        # that already-successful test process.
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        reader.join(timeout=2)
        raise SystemExit(0)
    if time.monotonic() >= deadline:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise SystemExit("Regression tests exceeded the 10-minute limit.")

reader.join(timeout=2)
raise SystemExit(process.returncode)
