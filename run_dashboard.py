"""Run the battery dashboard."""
import uvicorn
from pathlib import Path
from src.config import load_config
from src.dashboard.app import create_app

PROJECT_ROOT = Path(__file__).parent

config = load_config(PROJECT_ROOT / "config.yaml")
app = create_app(PROJECT_ROOT / "data" / "battery.db", config)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.dashboard.port)
