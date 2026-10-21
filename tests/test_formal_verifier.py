"""Unit tests for Formal SAT Verification (FormalControlVerifier and FormalWceVerifier)."""

import json
from pathlib import Path
import pytest
from axsys.verifier import FormalControlVerifier, FormalWceVerifier, MiterVerifier


@pytest.fixture
def sequential_rtl_fixture(tmp_path: Path):
    gold_path = tmp_path / "seq_gold.v"
    gold_path.write_text("""
    module seq_pipe (
        input  wire clk,
        input  wire rst_n,
        input  wire valid_in,
        input  wire [7:0] a,
        input  wire [7:0] b,
        output reg  valid_out,
        output wire [7:0] sum
    );
        assign sum = a + b;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) valid_out <= 1'b0;
            else        valid_out <= valid_in;
        end
    endmodule
    """)

    safe_approx_path = tmp_path / "seq_safe_approx.v"
    safe_approx_path.write_text("""
    module seq_pipe (
        input  wire clk,
        input  wire rst_n,
        input  wire valid_in,
        input  wire [7:0] a,
        input  wire [7:0] b,
        output reg  valid_out,
        output wire [7:0] sum
    );
        // Approximation on sum (dropped 2 LSBs)
        assign sum = {a[7:2] + b[7:2], 2'b00};
        // 100% exact control preservation
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) valid_out <= 1'b0;
            else        valid_out <= valid_in;
        end
    endmodule
    """)

    corrupted_control_path = tmp_path / "seq_corrupt_ctrl.v"
    corrupted_control_path.write_text("""
    module seq_pipe (
        input  wire clk,
        input  wire rst_n,
        input  wire valid_in,
        input  wire [7:0] a,
        input  wire [7:0] b,
        output reg  valid_out,
        output wire [7:0] sum
    );
        assign sum = a + b;
        // BUG: Inverted control logic!
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) valid_out <= 1'b1;
            else        valid_out <= ~valid_in;
        end
    endmodule
    """)

    meta_path = tmp_path / "seq_meta.json"
    meta_path.write_text(json.dumps({
        "top_module": "seq_pipe",
        "relaxed_signals": [
            {"wire": "sum", "width": 17, "metric": "WCE", "bound": 16.0, "lsb_width": 3}
        ]
    }))

    return {
        "gold": gold_path,
        "safe_approx": safe_approx_path,
        "corrupt_ctrl": corrupted_control_path,
        "meta": meta_path,
    }


def test_formal_control_verifier_proven(sequential_rtl_fixture):
    fix = sequential_rtl_fixture
    verifier = FormalControlVerifier(
        exact_vlog=fix["gold"],
        approx_vlog=fix["safe_approx"],
        meta_json=fix["meta"],
        induction_depth=5,
        timeout=30,
    )
    res = verifier.verify()
    assert res["status"] == "PROVEN"
    assert res["proven_forever"] is True
    assert "valid_out" in res["signals_checked"]


def test_formal_control_verifier_falsified(sequential_rtl_fixture):
    fix = sequential_rtl_fixture
    verifier = FormalControlVerifier(
        exact_vlog=fix["gold"],
        approx_vlog=fix["corrupt_ctrl"],
        meta_json=fix["meta"],
        induction_depth=5,
        timeout=30,
    )
    res = verifier.verify()
    assert res["status"] == "FALSIFIED"
    assert res["proven_forever"] is False
    assert "counterexample" in res


@pytest.fixture
def cone_rtl_fixture(tmp_path: Path):
    exact_cone = tmp_path / "exact_cone.v"
    exact_cone.write_text("""
    module sample_cone (
        input  wire [15:0] a,
        input  wire [15:0] b,
        output wire [16:0] sum
    );
        assign sum = a + b;
    endmodule
    """)

    # Truncated 3 LSBs: max arithmetic error is (7 + 7) = 14
    approx_cone = tmp_path / "approx_cone.v"
    approx_cone.write_text("""
    module sample_cone (
        input  wire [15:0] a,
        input  wire [15:0] b,
        output wire [16:0] sum
    );
        wire [13:0] high_sum = {1'b0, a[15:3]} + {1'b0, b[15:3]};
        assign sum = {high_sum, 3'b000};
    endmodule
    """)

    return {
        "exact": exact_cone,
        "approx": approx_cone,
    }


def test_formal_wce_prover_proven_within_bound(cone_rtl_fixture):
    fix = cone_rtl_fixture
    # The max error is 14. A bound of 15 should be formally PROVEN for all 2^32 inputs.
    meta = {
        "relaxed_signals": [
            {"wire": "sum", "width": 17, "bound": 15.0}
        ]
    }
    verifier = FormalWceVerifier(
        exact_cone_vlog=fix["exact"],
        approx_cone_vlog=fix["approx"],
        target_signals=meta["relaxed_signals"],
        timeout=30,
    )
    res = verifier.verify()
    assert res["status"] == "PROVEN"
    assert res["wce_bound_satisfied"] is True


def test_formal_wce_prover_falsified_when_exceeding_bound(cone_rtl_fixture):
    fix = cone_rtl_fixture
    # The max error is 14. A bound of 10 must be FALSIFIED by SAT.
    meta = {
        "relaxed_signals": [
            {"wire": "sum", "width": 17, "bound": 10.0}
        ]
    }
    verifier = FormalWceVerifier(
        exact_cone_vlog=fix["exact"],
        approx_cone_vlog=fix["approx"],
        target_signals=meta["relaxed_signals"],
        timeout=30,
    )
    res = verifier.verify()
    assert res["status"] == "FALSIFIED"
    assert res["wce_bound_satisfied"] is False


def test_miter_verifier_includes_formal_results(sequential_rtl_fixture, cone_rtl_fixture):
    seq_fix = sequential_rtl_fixture
    cone_fix = cone_rtl_fixture

    verifier = MiterVerifier(
        exact_vlog=seq_fix["gold"],
        approx_vlog=seq_fix["safe_approx"],
        meta_json=seq_fix["meta"],
        num_cycles=20,
        enable_formal=True,
        extracted_cone_vlog=cone_fix["exact"],
        approx_cone_vlog=cone_fix["approx"],
    )
    res = verifier.verify()
    assert res["status"] == "PASSED"
    assert "formal_verification" in res
    fv = res["formal_verification"]
    assert fv["control_equivalence"]["status"] == "PROVEN"
    assert fv["wce_bound"]["status"] == "PROVEN"
