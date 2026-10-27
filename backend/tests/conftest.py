import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from app import facts as F
from app.config_loader import load_config


@pytest.fixture(scope="session")
def cfg():
    c0 = load_config(strict=False)
    return load_config(known_facts=F.fact_catalog(c0), strict=False)
