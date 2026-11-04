"""Build the optimized portable release; model weights download on demand."""
import runpy
import sys
from pathlib import Path

if __name__ == '__main__':
    sys.argv = [__file__, '--release', '--zip', '--update']
    runpy.run_path(str(Path(__file__).with_name('build_lite.py')), run_name='__main__')
