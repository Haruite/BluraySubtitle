"""Migration entrypoint.

Supports both:
- `python -m src.main`
- `python src/main.py`
"""

try:
    from .runtime.bootstrap import main
except ImportError:
    import os
    import sys

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from src.runtime.bootstrap import main


if __name__ == "__main__":
    main()

