"""Unit tests for MiterVerifier module."""

import json
from pathlib import Path
import pytest
from axsys.verifier import MiterVerifier


@pytest.fixture
def sample_exact_vlog(tmp_path: Path) -> Path:
    p = tmp_path / "sample_exact.v"
    p.write_text("""
    module sample_alu (
        input  wire        clk,
        input  wire        rst_n,
        (* axc_precise = "1" *) input  wire valid_in,
        (* axc_precise = "1" *) output reg  valid_out,
        input  wire signed [7:0] a,
        input  wire signed [7:0] b,
        (* axc_relax = "1", axc_metric = "MED", axc_bound = "5.0", axc_lsb_width = 4 *)
        output wire signed [8:0] sum
    );
        assign sum = a + b;

        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) valid_out <= 1'b0;
            else        valid_out <= valid_in;
        end
    endmodule
    """)
    return p


@pytest.fixture
def sample_meta_json(tmp_path: Path) -> Path:
    p = tmp_path / "sample_meta.json"
    meta = {
        "top_module": "sample_alu",
        "relaxed_signals": [
            {
                "wire": "sum",
                "width": 9,
                "metric": "MED",
                "bound": 5.0,
                "lsb_width": 4,
            }
        ],
    }
    p.write_text(json.dumps(meta, indent=2))
    return p


def test_verifier_port_inspection(sample_exact_vlog: Path, sample_meta_json: Path):
    verifier = MiterVerifier(
        exact_vlog=sample_exact_vlog,
        approx_vlog=sample_exact_vlog,
        meta_json=sample_meta_json,
        tech="NanGate15nm",
        num_cycles=50,
    )
    ports = verifier._inspect_module_ports()

    input_names = [p["name"] for p in ports["inputs"]]
    output_names = [p["name"] for p in ports["outputs"]]

    assert "clk" in input_names
    assert "rst_n" in input_names
    assert "a" in input_names
    assert "b" in input_names
    assert "valid_in" in input_names
    assert "valid_out" in output_names
    assert "sum" in output_names

    # Check signedness recognition
    a_port = next(p for p in ports["inputs"] if p["name"] == "a")
    assert a_port["is_signed"] is True
    assert a_port["width"] == 8

    sum_port = next(p for p in ports["outputs"] if p["name"] == "sum")
    assert sum_port["is_signed"] is True
    assert sum_port["width"] == 9


def test_verifier_rename_approx_netlist(sample_exact_vlog: Path, sample_meta_json: Path, tmp_path: Path):
    verifier = MiterVerifier(
        exact_vlog=sample_exact_vlog,
        approx_vlog=sample_exact_vlog,
        meta_json=sample_meta_json,
        tech="NanGate15nm",
        num_cycles=50,
    )
    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    renamed = verifier._prepare_approx_netlist(work_dir)

    assert renamed.exists()
    content = renamed.read_text()
    assert "module sample_alu_approx" in content


def test_verifier_testbench_generation(sample_exact_vlog: Path, sample_meta_json: Path, tmp_path: Path):
    verifier = MiterVerifier(
        exact_vlog=sample_exact_vlog,
        approx_vlog=sample_exact_vlog,
        meta_json=sample_meta_json,
        tech="NanGate15nm",
        num_cycles=50,
    )
    ports = verifier._inspect_module_ports()
    tb_path = verifier.generate_miter_tb(tmp_path, ports)

    assert tb_path.exists()
    tb_text = tb_path.read_text()
    assert "module tb_miter;" in tb_text
    assert "sample_alu uut_exact (" in tb_text
    assert "sample_alu_approx uut_approx (" in tb_text
    assert "total_error_distance_sum" in tb_text
    assert "signed [7:0] a;" in tb_text


def test_verifier_exact_vs_exact_passes(sample_exact_vlog: Path, sample_meta_json: Path):
    verifier = MiterVerifier(
        exact_vlog=sample_exact_vlog,
        approx_vlog=sample_exact_vlog,
        meta_json=sample_meta_json,
        tech="NanGate15nm",
        num_cycles=50,
    )
    res = verifier.verify()

    assert res["status"] == "PASSED"
    assert res["control_integrity"] == "PASSED"
    assert res["control_errors"] == 0
    assert res["measured_med"] == 0.0
    assert res["measured_wce"] == 0.0
    assert res["error_bound_satisfied"] is True


def test_verifier_unsupported_metric_rejected(sample_exact_vlog: Path, tmp_path: Path):
    bad_meta_path = tmp_path / "bad_meta.json"
    bad_meta = {
        "top_module": "sample_alu",
        "relaxed_signals": [
            {
                "wire": "sum",
                "width": 9,
                "metric": "UNKNOWN_METRIC",
                "bound": 1.0,
            }
        ],
    }
    bad_meta_path.write_text(json.dumps(bad_meta, indent=2))

    verifier = MiterVerifier(
        exact_vlog=sample_exact_vlog,
        approx_vlog=sample_exact_vlog,
        meta_json=bad_meta_path,
        tech="NanGate15nm",
        num_cycles=50,
    )
    res = verifier.verify()

    assert res["status"] == "FAILED"
    metric_evals = res.get("metric_evaluations", [])
    assert len(metric_evals) == 1
    assert metric_evals[0]["satisfied"] is False
    assert "Unsupported metric" in metric_evals[0].get("error", "")
