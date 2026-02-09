import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SAMPLE_G28_URL = "https://alma-public-assets.s3.us-west-2.amazonaws.com/interview/Example_G-28.pdf"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
LOCAL_G28_PATH = FIXTURES_DIR / "Example_G-28.pdf"
LOCAL_FORM_PATH = FIXTURES_DIR / "form.html"
SYNTHETIC_PASSPORT_PATH = FIXTURES_DIR / "synthetic_passport_mrz.png"
SYNTHETIC_PASSPORT_JPG_PATH = FIXTURES_DIR / "synthetic_passport_mrz.jpg"
SYNTHETIC_PASSPORT_REALISTIC_PATH = FIXTURES_DIR / "synthetic_passport_mrz_realistic.png"
GOLD_PASSPORT_PATH = FIXTURES_DIR / "gold_passport.png"
SYNTHETIC_G28_PATH = FIXTURES_DIR / "synthetic_g28_text.png"
SYNTHETIC_G28_BLUR_PATH = FIXTURES_DIR / "synthetic_g28_text_blurred.png"


@pytest.fixture(scope="session")
def sample_g28_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if LOCAL_G28_PATH.exists():
        return LOCAL_G28_PATH

    target_dir = tmp_path_factory.mktemp("fixtures")
    target_path = target_dir / "Example_G-28.pdf"
    try:
        resp = requests.get(SAMPLE_G28_URL, timeout=30)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Unable to locate sample G-28 PDF and download failed: {exc}")
    target_path.write_bytes(resp.content)
    return target_path


@pytest.fixture(scope="session")
def form_fixture_url() -> str:
    if not LOCAL_FORM_PATH.exists():
        pytest.fail(f"Local form fixture missing at {LOCAL_FORM_PATH}")
    return LOCAL_FORM_PATH.resolve().as_uri()


@pytest.fixture(scope="session")
def synthetic_passport_path() -> Path:
    if not SYNTHETIC_PASSPORT_PATH.exists():
        pytest.fail(f"Synthetic passport fixture missing at {SYNTHETIC_PASSPORT_PATH}")
    return SYNTHETIC_PASSPORT_PATH


@pytest.fixture(scope="session")
def synthetic_passport_jpg_path() -> Path:
    if not SYNTHETIC_PASSPORT_JPG_PATH.exists():
        pytest.fail(f"Synthetic passport JPG fixture missing at {SYNTHETIC_PASSPORT_JPG_PATH}")
    return SYNTHETIC_PASSPORT_JPG_PATH


@pytest.fixture(scope="session")
def realistic_passport_path() -> Path:
    if not SYNTHETIC_PASSPORT_REALISTIC_PATH.exists():
        pytest.fail(f"Realistic passport fixture missing at {SYNTHETIC_PASSPORT_REALISTIC_PATH}")
    return SYNTHETIC_PASSPORT_REALISTIC_PATH


@pytest.fixture(scope="session")
def gold_passport_path() -> Path:
    if not GOLD_PASSPORT_PATH.exists():
        pytest.fail(f"Gold passport fixture missing at {GOLD_PASSPORT_PATH}")
    return GOLD_PASSPORT_PATH


@pytest.fixture(scope="session")
def synthetic_g28_path() -> Path:
    if not SYNTHETIC_G28_PATH.exists():
        pytest.fail(f"Synthetic G-28 fixture missing at {SYNTHETIC_G28_PATH}")
    return SYNTHETIC_G28_PATH


@pytest.fixture(scope="session")
def synthetic_g28_blur_path() -> Path:
    if not SYNTHETIC_G28_BLUR_PATH.exists():
        pytest.fail(f"Synthetic blurred G-28 fixture missing at {SYNTHETIC_G28_BLUR_PATH}")
    return SYNTHETIC_G28_BLUR_PATH
