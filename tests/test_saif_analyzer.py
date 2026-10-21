"""Unit tests for SaifPowerAnalyzer."""

from pathlib import Path
import tempfile
import pytest

from axsys.saif_analyzer import SaifPowerAnalyzer

REPO_ROOT = Path(__file__).resolve().parent.parent
TECH_LIB = REPO_ROOT / "third_party" / "AxLS" / "templates" / "NanGate15nm.lib"
TECH_V = REPO_ROOT / "third_party" / "AxLS" / "templates" / "NanGate15nm.v"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "saif"
FIR_EXACT = FIXTURES_DIR / "exact_baseline_mapped.v"
FIR_APPROX = FIXTURES_DIR / "final_approx_top.v"


def test_saif_analyzer_init():
    analyzer = SaifPowerAnalyzer(TECH_LIB, TECH_V)
    assert len(analyzer.cell_models) > 20
    assert "INV_X1" in analyzer.cell_models
    inv_model = analyzer.cell_models["INV_X1"]
    assert "I" in inv_model["input_pins"]
    assert inv_model["input_pins"]["I"] > 0.0


def test_saif_analyzer_simulation_and_evaluation():
    analyzer = SaifPowerAnalyzer(TECH_LIB, TECH_V)
    with tempfile.TemporaryDirectory(prefix="pytest_saif_") as tmp:
        work_dir = Path(tmp)
        cmp_res = analyzer.compare_exact_vs_approx(
            exact_netlist=FIR_EXACT,
            approx_netlist=FIR_APPROX,
            top_module="fir",
            work_dir=work_dir,
            num_cycles=200,
        )

        assert cmp_res["top_module"] == "fir"
        assert cmp_res["exact"]["total_cells"] == 587
        assert cmp_res["approx"]["total_cells"] < 587
        assert cmp_res["saif_total_savings_percent"] > 0.0
        assert cmp_res["saif_dyn_savings_percent"] > 0.0
        assert Path(cmp_res["exact"]["saif_path"]).exists()
        assert Path(cmp_res["approx"]["saif_path"]).exists()
