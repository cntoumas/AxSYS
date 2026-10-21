"""Unit tests for AxlsBridge Tournament and Backend Selection (Phase 3)."""

from pathlib import Path
import pytest
from axsys.axls_bridge import AxlsBridge


@pytest.fixture
def sample_adder(tmp_path: Path) -> Path:
    cone_v = tmp_path / "sample_add.v"
    cone_v.write_text("""
    module sample_add (
        input wire [3:0] a,
        input wire [3:0] b,
        output wire [4:0] y
    );
        assign y = a + b;
    endmodule
    """)
    return cone_v


def test_tournament_auto_mode(sample_adder: Path, tmp_path: Path):
    out_approx = tmp_path / "approx_tournament.v"
    bridge = AxlsBridge(
        cone_verilog_path=sample_adder,
        tech="NanGate15nm",
        samples=40,
        work_dir=tmp_path / "work_tourn",
    )
    res = bridge.optimize(
        metric="med",
        bound=1.0,
        lsb_width=2,
        method="auto",
        out_approx_path=out_approx,
        isolated=True,
    )

    assert res["status"] == "SUCCESS"
    assert out_approx.exists()
    assert res["method"] == "auto"
    assert "champion_method" in res
    assert res["champion_method"] in ("inouts", "probprun", "decisiontree")
    assert "leaderboard" in res
    assert len(res["leaderboard"]) >= 2

    # Check leaderboard structure
    methods = [entry["method"] for entry in res["leaderboard"]]
    assert "inouts" in methods
    assert "probprun" in methods


def test_probprun_direct(sample_adder: Path, tmp_path: Path):
    out_approx = tmp_path / "approx_probprun.v"
    bridge = AxlsBridge(
        cone_verilog_path=sample_adder,
        tech="NanGate15nm",
        samples=40,
        work_dir=tmp_path / "work_prob",
    )
    res = bridge.optimize(
        metric="med",
        bound=1.0,
        method="probprun",
        out_approx_path=out_approx,
        isolated=True,
    )

    assert res["status"] == "SUCCESS"
    assert out_approx.exists()
    assert res["champion_method"] == "probprun"
    assert "final_area" in res


def test_inouts_direct(sample_adder: Path, tmp_path: Path):
    out_approx = tmp_path / "approx_inouts.v"
    bridge = AxlsBridge(
        cone_verilog_path=sample_adder,
        tech="NanGate15nm",
        samples=40,
        work_dir=tmp_path / "work_inouts",
    )
    res = bridge.optimize(
        metric="med",
        bound=1.0,
        lsb_width=2,
        method="inouts",
        out_approx_path=out_approx,
        isolated=True,
    )

    assert res["status"] == "SUCCESS"
    assert out_approx.exists()
    assert res["champion_method"] == "inouts"
    assert "area_savings_percent" in res
