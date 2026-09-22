"""运行 ATR 参数扫描：python scripts/scan_atr_exit_mult.py --course-module /path/to/course_adapter.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.cli import main


if __name__ == "__main__":
    main()
