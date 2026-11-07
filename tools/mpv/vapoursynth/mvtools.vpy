from pathlib import Path
from runpy import run_path

filters = run_path(str(Path(__file__).with_name("filters.py")))
filters["mvtools"](video_in, container_fps, globals().get("user_data", "")).set_output()
