from pathlib import Path
from runpy import run_path

filters = run_path(str(Path(__file__).with_name("filters.py")))
filters["bm3d"](video_in).set_output()
