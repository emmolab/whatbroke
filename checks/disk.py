import os
import shutil
import sys

# Add parent directory to path for local development
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from result import Result

def check():
    total, used, free = shutil.disk_usage("/")
    percent_used = used / total * 100

    if percent_used > 95:
        status = "BROKE"
    elif percent_used > 85:
        status = "WARN"
    else:
        status = "OK"

    return Result(
        name="disk",
        status=status,
        message=f"Root filesystem {percent_used:.1f}% used",
    )
