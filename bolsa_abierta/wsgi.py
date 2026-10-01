import os
from pathlib import Path

from .server import Application
from .store import Store

root = Path(__file__).resolve().parents[1]
app = Application(Store(os.environ.get('BA_DATA_DIR', root / '.runtime'), root / 'data/state.json'), root)
