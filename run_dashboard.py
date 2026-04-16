"""Run the battery dashboard."""
import uvicorn
from pathlib import Path
from src.dashboard.app import create_app

app = create_app(Path(__file__).parent / "data" / "battery.db")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8099)
