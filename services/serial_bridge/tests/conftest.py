import shutil, subprocess, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def firmware(tmp_path_factory):
    """Real smart_parking.ino compiled for the PC with the hostsim shim."""
    if not shutil.which("g++"):
        pytest.skip("g++ not available")
    exe = tmp_path_factory.mktemp("fw") / "fw"
    sim = ROOT / "tools" / "hostsim"
    subprocess.run(["g++", "-std=c++17", "-O1", f"-I{sim}", "-o", str(exe), str(sim / "harness.cpp")], check=True)

    def run(script: str) -> list[str]:
        out = subprocess.run([str(exe)], input=script, capture_output=True, text=True, timeout=60).stdout
        return out.splitlines()
    return run
