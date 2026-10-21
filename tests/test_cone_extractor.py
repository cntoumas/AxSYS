"""Unit tests for Pyosys RTLIL Cone Extractor."""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest
from axsys.cone_extractor import ConeExtractor


def test_mac_pe_extraction(tmp_path: Path):
    rtl_path = tmp_path / "mac_pe.v"
    rtl_path.write_text(
        """
        module mac_pe (
            input  wire        clk,
            input  wire        rst_n,
            (* axc_precise = "1" *) input  wire        valid_in,
            (* axc_precise = "1" *) output reg         valid_out,
            input  wire signed [7:0] a,
            input  wire signed [7:0] b,
            input  wire signed [15:0] c,
            (* axc_relax = "1", axc_metric = "MED", axc_bound = "0.015", axc_lsb_width = 8 *)
            output wire signed [16:0] y
        );
            assign y = (a * b) + c;
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) valid_out <= 1'b0;
                else        valid_out <= valid_in;
            end
        endmodule
        """
    )
    out_submod = tmp_path / "submod.v"
    out_top = tmp_path / "top_shell.v"
    out_meta = tmp_path / "meta.json"

    extractor = ConeExtractor(verilog_path=rtl_path)
    result = extractor.extract_safe_cone(
        submod_tag="axc_cone_0",
        out_submod_path=out_submod,
        out_top_path=out_top,
        out_meta_path=out_meta,
    )

    assert result["status"] == "SUCCESS"
    assert result["top_module"] == "mac_pe"
    assert result["num_safe_cells"] == 2
    assert "$add" in result["cell_types"]
    assert "$mul" in result["cell_types"]
    assert len(result["relaxed_signals"]) == 1
    assert result["relaxed_signals"][0]["metric"] == "MED"
    assert result["relaxed_signals"][0]["bound"] == 0.015

    assert out_submod.exists()
    assert out_top.exists()
    assert out_meta.exists()

    # Verify separated netlists compile with iverilog
    compile_cmd = ["iverilog", "-g2012", "-o", str(tmp_path / "sim.vvp"), str(out_submod), str(out_top)]
    proc = subprocess.run(compile_cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"iverilog compilation failed: {proc.stderr}"


def test_shared_logic_taint_protection(tmp_path: Path):
    shared_vlog = tmp_path / "shared_design.v"
    shared_vlog.write_text(
        """
        module shared_design (
            input  wire [7:0] a,
            input  wire [7:0] b,
            (* axc_relax = "1", axc_metric = "MED", axc_bound = "0.02" *)
            output wire [15:0] y,
            (* axc_precise = "1" *)
            output wire is_zero
        );
            wire [15:0] prod = a * b;
            assign y = prod;
            assign is_zero = (prod == 16'd0);
        endmodule
        """
    )

    extractor = ConeExtractor(verilog_path=shared_vlog)
    result = extractor.extract_safe_cone(submod_tag="axc_cone_0")

    # Since the multiplier feeds both relaxed y and precise is_zero,
    # taint protection must exclude the multiplier from C_safe.
    assert result["status"] == "TAINTED_EMPTY_SAFE_SET"
    assert len(result["safe_cells"]) == 0


def test_independent_cones(tmp_path: Path):
    vlog = tmp_path / "independent.v"
    vlog.write_text(
        """
        module independent (
            input  wire [7:0] a,
            input  wire [7:0] b,
            input  wire [7:0] c,
            input  wire [7:0] d,
            (* axc_relax = "1", axc_metric = "WCE", axc_bound = "4" *)
            output wire [7:0] sum_approx,
            (* axc_precise = "1" *)
            output wire [7:0] sum_exact
        );
            assign sum_approx = a + b;
            assign sum_exact = c + d;
        endmodule
        """
    )

    extractor = ConeExtractor(verilog_path=vlog)
    result = extractor.extract_safe_cone(
        submod_tag="axc_cone_0",
        out_submod_path=tmp_path / "sub.v",
        out_top_path=tmp_path / "top.v"
    )

    assert result["status"] == "SUCCESS"
    assert result["num_safe_cells"] == 1
    assert "$add" in result["cell_types"]
    assert result["relaxed_signals"][0]["metric"] == "WCE"
    assert result["relaxed_signals"][0]["bound"] == 4.0


def test_bit_level_slicing_with_decomposition(tmp_path: Path):
    rtl_path = tmp_path / "sliced_adder.v"
    rtl_path.write_text(
        """
        module sliced_adder (
            input  wire [15:0] a,
            input  wire [15:0] b,
            (* axc_relax = "1", axc_metric = "MED", axc_bound = "8.0", axc_lsb_width = 8 *)
            output wire [15:0] sum,
            (* axc_precise = "1" *)
            output wire        overflow
        );
            assign {overflow, sum} = a + b;
        endmodule
        """
    )
    out_submod = tmp_path / "submod_sliced.v"
    out_top = tmp_path / "top_sliced.v"
    out_meta = tmp_path / "meta_sliced.json"

    extractor = ConeExtractor(verilog_path=rtl_path, decompose_operators=True)
    result = extractor.extract_safe_cone(
        submod_tag="axc_cone_0",
        out_submod_path=out_submod,
        out_top_path=out_top,
        out_meta_path=out_meta,
    )

    assert result["status"] == "SUCCESS"
    assert result["num_safe_cells"] > 0
    # Bit-level cells decomposed
    assert any(t.startswith("$_") or t in ("$xor", "$and") for t in result["cell_types"].keys())
    assert out_submod.exists()
    assert out_top.exists()
    assert out_meta.exists()

    # Verify separated netlists compile cleanly with iverilog
    compile_cmd = ["iverilog", "-g2012", "-o", str(tmp_path / "sim_sliced.vvp"), str(out_submod), str(out_top)]
    proc = subprocess.run(compile_cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"iverilog compilation failed: {proc.stderr}"


def test_disjoint_multi_cone_partitioning(tmp_path: Path):
    rtl_path = tmp_path / "multi_cones.v"
    rtl_path.write_text(
        """
        module multi_cones (
            input  wire [7:0] a,
            input  wire [7:0] b,
            input  wire [7:0] c,
            input  wire [7:0] d,
            (* axc_relax = "1", axc_metric = "MED", axc_bound = "4.0" *)
            output wire [7:0] sum_out,
            (* axc_relax = "1", axc_metric = "WCE", axc_bound = "8.0" *)
            output wire [15:0] prod_out
        );
            assign sum_out = a + b;
            assign prod_out = c * d;
        endmodule
        """
    )
    out_submod = tmp_path / "submod_multi.v"
    out_top = tmp_path / "top_multi.v"

    extractor = ConeExtractor(verilog_path=rtl_path)
    result = extractor.extract_safe_cone(
        submod_tag="axc_cone",
        out_submod_path=out_submod,
        out_top_path=out_top,
    )

    assert result["status"] == "SUCCESS"
    assert len(result["cones"]) == 2
    cone_tags = [c["tag"] for c in result["cones"]]
    assert "axc_cone_0" in cone_tags
    assert "axc_cone_1" in cone_tags

    # Verify separated netlists compile cleanly with iverilog
    compile_cmd = ["iverilog", "-g2012", "-o", str(tmp_path / "sim_multi.vvp"), str(out_submod), str(out_top)]
    proc = subprocess.run(compile_cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"iverilog compilation failed: {proc.stderr}"


def test_sequential_feedback_loop_detection(tmp_path: Path):
    rtl_path = tmp_path / "accumulator.v"
    rtl_path.write_text(
        """
        module accumulator (
            input  wire        clk,
            input  wire        rst_n,
            input  wire [7:0]  data_in,
            (* axc_relax = "1", axc_metric = "MED", axc_bound = "4.0" *)
            output reg  [7:0]  acc_out
        );
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n)
                    acc_out <= 8'd0;
                else
                    acc_out <= acc_out + data_in;
            end
        endmodule
        """
    )

    extractor = ConeExtractor(verilog_path=rtl_path)
    result = extractor.extract_safe_cone()

    assert result["status"] == "SUCCESS"
    assert result["has_sequential_feedback"] is True
    assert len(result["feedback_registers"]) > 0
    assert any("acc_out" in r for r in result["feedback_registers"])
