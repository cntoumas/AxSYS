"""Unit tests for Pareto Sweeper module (Phase 3)."""

from pathlib import Path
import pytest
from axsys.sweep import ParetoSweeper


@pytest.fixture
def sample_pe(tmp_path: Path) -> Path:
    pe_v = tmp_path / "simple_pe.v"
    pe_v.write_text("""
    module simple_pe (
        input wire clk,
        input wire rst_n,
        (* axc_precise = "1" *) input wire valid_in,
        (* axc_precise = "1" *) output reg valid_out,
        input wire [3:0] a,
        input wire [3:0] b,
        (* axc_relax = "1", axc_metric = "MED", axc_bound = "2.0", axc_lsb_width = 2 *)
        output wire [4:0] y
    );
        assign y = a + b;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) valid_out <= 1'b0;
            else        valid_out <= valid_in;
        end
    endmodule
    """)
    return pe_v


def test_parse_bounds(tmp_path: Path):
    sweeper = ParetoSweeper("dummy.v", str(tmp_path / "dummy_out"))
    res1 = sweeper.parse_bounds("1.0, 4.0, 2.0, 8.0")
    assert res1 == [1.0, 2.0, 4.0, 8.0]

    res2 = sweeper.parse_bounds([16, 4, 8])
    assert res2 == [4.0, 8.0, 16.0]


def test_pareto_sweep_execution(sample_pe: Path, tmp_path: Path):
    out_dir = tmp_path / "sweep_out"
    sweeper = ParetoSweeper(
        input_verilog=sample_pe,
        output_dir=out_dir,
        method="inouts",
        sim_samples=30,
        verify_cycles=30,
        enable_formal=True,
    )
    res = sweeper.run_sweep(bounds="1.0, 4.0")

    assert res["sweep_status"] == "SUCCESS"
    assert res["total_points"] == 2
    assert len(res["results"]) == 2

    # Check generated files
    csv_path = out_dir / "pareto_results.csv"
    json_path = out_dir / "pareto_summary.json"
    plot_path = out_dir / "pareto_curve.png"

    assert csv_path.exists()
    assert json_path.exists()
    assert plot_path.exists()
    assert plot_path.stat().st_size > 1000

    csv_text = csv_path.read_text()
    assert "bound" in csv_text
    assert "approx_area" in csv_text
    assert "area_savings_percent" in csv_text
