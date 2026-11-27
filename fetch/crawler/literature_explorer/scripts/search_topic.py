"""Legacy command entry for the shared literature explorer."""
from pathlib import Path
from runpy import run_path

if __name__ == "__main__":
    source = Path(__file__).resolve().parents[5] / "tools/literature_explorer/literature_explorer/scripts"
    run_path(str(source / Path(__file__).name), run_name="__main__")
