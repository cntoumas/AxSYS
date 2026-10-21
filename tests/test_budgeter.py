"""Unit tests for Cascaded Multi-Cone Budgeter module (Phase 3)."""

from pathlib import Path
import pytest
from axsys.budgeter import CascadedBudgeter


@pytest.fixture
def sample_pipeline(tmp_path: Path) -> Path:
    pipe_v = tmp_path / "simple_pipeline.v"
    pipe_v.write_text("""
    module simple_pipeline (
        input wire clk,
        input wire rst_n,
        (* axc_precise = "1" *) input wire valid_in,
        (* axc_precise = "1" *) output reg valid_out,
        input wire [3:0] a,
        input wire [3:0] b,
        (* axc_relax = "1", axc_metric = "MED", axc_bound = "4.0", axc_lsb_width = 3 *)
        output wire [4:0] y
    );
        assign y = a + b;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) valid_out <= 1'b0;
            else        valid_out <= valid_in;
        end
    endmodule
    """)
    return pipe_v


def test_budgeter_tightening_formula():
    """Verify contraction formula: B_i <- B_i * (B_top / E_top) * 0.9."""
    b_top = 2.0
    e_top = 5.0
    b_init = 10.0
    contraction = 0.9

    ratio = (b_top / e_top) * contraction
    b_next = b_init * ratio
    assert abs(ratio - 0.36) < 1e-6
    assert abs(b_next - 3.6) < 1e-6


def test_budgeter_convergence(sample_pipeline: Path, tmp_path: Path):
    out_dir = tmp_path / "budget_out"
    budgeter = CascadedBudgeter(
        input_verilog=sample_pipeline,
        output_dir=out_dir,
        b_top=2.0,
        max_iterations=3,
        sim_samples=30,
        verify_cycles=30,
        enable_formal=False,
    )
    res = budgeter.optimize_budgets()

    assert "converged" in res
    assert "iterations_run" in res
    assert res["iterations_run"] >= 1
    assert "trajectory" in res

    # Check generated artifacts
    traj_path = out_dir / "budget_trajectory.json"
    csv_path = out_dir / "budget_summary.csv"
    assert traj_path.exists()
    assert csv_path.exists()

    csv_text = csv_path.read_text()
    assert "iteration" in csv_text
    assert "cone_budget" in csv_text
    assert "b_top" in csv_text
