import runpy
from pathlib import Path

SCRIPTS = ["load_data", "analysis", "scheduler", "rooms", "sensitivity", "projection", "dashboard", "excel_report"]

for name in SCRIPTS:
    print(f"\n=== {name}.py ===")
    runpy.run_path(str(Path(__file__).parent / f"{name}.py"), run_name="__main__")
