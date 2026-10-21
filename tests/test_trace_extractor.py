"""Unit tests for realistic pipeline TraceExtractor module."""

import json
from pathlib import Path
import pytest
from pyosys import libyosys as ys
from axsys.cone_extractor import ConeExtractor
from axsys.trace_extractor import TraceExtractor
from axsys.axls_bridge import AxlsBridge


@pytest.fixture
def pipeline_fixture(tmp_path: Path):
    vlog_path = tmp_path / "mac_pipe.v"
    vlog_path.write_text("""
    module mac_pipe (
        input  wire clk,
        input  wire rst_n,
        (* axc_precise = "1" *) input  wire valid_in,
        (* axc_precise = "1" *) output reg  valid_out,
        input  wire [7:0] a,
        input  wire [7:0] b,
        (* axc_relax = "1", axc_metric = "MED", axc_bound = "16.0", axc_lsb_width = 4 *)
        output reg  [15:0] acc
    );
        reg [7:0] a_reg, b_reg;
        wire [15:0] mult_res = a_reg * b_reg;

        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                valid_out <= 1'b0;
                a_reg <= 8'd0;
                b_reg <= 8'd0;
                acc <= 16'd0;
            end else begin
                valid_out <= valid_in;
                a_reg <= a;
                b_reg <= b;
                acc <= acc + mult_res;
            end
        end
    endmodule
    """)
    return vlog_path


def test_trace_extractor_inspect_and_dump(pipeline_fixture: Path, tmp_path: Path):
    # 1. Extract cone first
    submod_vlog = tmp_path / "extracted_cone.v"
    top_shell_vlog = tmp_path / "top_shell.v"
    meta_json = tmp_path / "cone_meta.json"

    extractor = ConeExtractor(verilog_path=pipeline_fixture)
    cone_res = extractor.extract_safe_cone(
        submod_tag="axc_cone_0",
        out_submod_path=submod_vlog,
        out_top_path=top_shell_vlog,
        out_meta_path=meta_json,
    )
    assert cone_res["status"] == "SUCCESS"

    # 2. Extract traces
    trace_hex = tmp_path / "cone_trace.hex"
    tracer = TraceExtractor(
        top_shell_path=top_shell_vlog,
        extracted_cone_path=submod_vlog,
        meta_json=meta_json,
    )

    info = tracer._inspect_circuit()
    assert info["top_name"] == "mac_pipe"
    assert info["clk_name"] == "clk"
    assert info["rst_name"] == "rst_n"
    assert info["valid_in_name"] == "valid_in"
    assert len(info["cone_inputs"]) > 0

    res = tracer.extract_traces(
        out_trace_hex=trace_hex,
        num_samples=25,
        clk_period_ns=10.0,
    )

    assert res["status"] == "SUCCESS"
    assert res["num_vectors"] == 25
    assert trace_hex.exists()

    content = trace_hex.read_text(encoding="utf-8")
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    assert lines[0].startswith("#")  # Header with column names
    data_lines = [l for l in lines if not l.startswith("#")]
    assert len(data_lines) == 25


def test_axls_bridge_with_trace_dataset(pipeline_fixture: Path, tmp_path: Path):
    submod_vlog = tmp_path / "extracted_cone.v"
    top_shell_vlog = tmp_path / "top_shell.v"
    meta_json = tmp_path / "cone_meta.json"

    extractor = ConeExtractor(verilog_path=pipeline_fixture)
    cone_res = extractor.extract_safe_cone(
        submod_tag="axc_cone_0",
        out_submod_path=submod_vlog,
        out_top_path=top_shell_vlog,
        out_meta_path=meta_json,
    )

    trace_hex = tmp_path / "cone_trace.hex"
    tracer = TraceExtractor(
        top_shell_path=top_shell_vlog,
        extracted_cone_path=submod_vlog,
        meta_json=meta_json,
    )
    trace_res = tracer.extract_traces(
        out_trace_hex=trace_hex,
        num_samples=30,
    )
    assert trace_res["status"] == "SUCCESS"

    # Now pass the extracted trace into AxlsBridge
    bridge = AxlsBridge(
        cone_verilog_path=submod_vlog,
        tech="NanGate15nm",
        samples=30,
        work_dir=tmp_path / "axls_work",
        trace_hex_path=trace_hex,
    )

    approx_vlog = tmp_path / "approx_cone.v"
    opt_res = bridge.optimize(
        metric="med",
        bound=16.0,
        lsb_width=4,
        out_approx_path=approx_vlog,
    )

    assert opt_res["status"] == "SUCCESS"
    assert approx_vlog.exists()
