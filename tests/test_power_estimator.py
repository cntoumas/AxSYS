"""Unit tests for Liberty standard-cell Power Estimator."""

from pathlib import Path
import pytest
from axsys.power_estimator import PowerEstimator


def test_power_estimator_liberty_parsing():
    estimator = PowerEstimator(tech="NanGate15nm")
    assert len(estimator.cell_models) > 0
    assert "AND2_X1" in estimator.cell_models
    assert "DFFRNQ_X1" in estimator.cell_models

    and2 = estimator.cell_models["AND2_X1"]
    assert and2["area"] > 0.0
    assert and2["leakage_uw"] > 0.0
    assert and2["pin_cap_ff"] > 0.0


def test_power_estimator_netlist_evaluation(tmp_path: Path):
    estimator = PowerEstimator(tech="NanGate15nm")
    
    # Create dummy netlist
    netlist = tmp_path / "dummy_mapped.v"
    netlist.write_text("""
    module dummy (A, B, Y);
      input A, B;
      output Y;
      AND2_X1 g1 (.A1(A), .A2(B), .ZN(Y));
      XOR2_X1 g2 (.A(A), .B(B), .Z(Y));
      INV_X1  g3 (.A(A), .ZN(Y));
    endmodule
    """)

    res = estimator.evaluate_netlist(netlist, alpha=0.25, vdd=0.8, clk_mhz=100.0)
    assert res["cell_count"] == 3
    assert res["leakage_power_uw"] > 0.0
    assert res["dynamic_power_uw"] > 0.0
    assert res["total_power_uw"] == pytest.approx(res["leakage_power_uw"] + res["dynamic_power_uw"], rel=1e-3)


def test_power_estimator_comparison(tmp_path: Path):
    estimator = PowerEstimator(tech="NanGate15nm")
    
    exact_netlist = tmp_path / "exact.v"
    exact_netlist.write_text("""
    module exact (A, B, Y);
      input A, B;
      output Y;
      AND2_X1 g1 (.A1(A), .A2(B), .ZN(Y));
      AND2_X1 g2 (.A1(A), .A2(B), .ZN(Y));
      XOR2_X1 g3 (.A(A), .B(B), .Z(Y));
      INV_X1  g4 (.A(A), .ZN(Y));
    endmodule
    """)

    approx_netlist = tmp_path / "approx.v"
    approx_netlist.write_text("""
    module approx (A, B, Y);
      input A, B;
      output Y;
      AND2_X1 g1 (.A1(A), .A2(B), .ZN(Y));
      INV_X1  g4 (.A(A), .ZN(Y));
    endmodule
    """)

    comp = estimator.compare_power(exact_netlist, approx_netlist)
    assert comp["cells_pruned"] == 2
    assert comp["total_power_savings_percent"] > 0.0
    assert comp["area_savings_percent"] > 0.0
