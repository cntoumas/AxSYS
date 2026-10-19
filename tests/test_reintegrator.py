"""Unit tests for Reintegrator module."""

import json
from pathlib import Path
import pytest
from axsys.reintegrator import Reintegrator, TECH_V_DEFAULT


def test_reintegrator_hierarchical(tmp_path: Path):
    top_shell = tmp_path / "top_shell.v"
    top_shell.write_text("""
    module top_shell (
        input wire [7:0] a,
        input wire [7:0] b,
        output wire [8:0] y
    );
        axc_cone_0 inst_sub (
            .a(a),
            .b(b),
            .y(y)
        );
    endmodule
    """)

    approx_cone = tmp_path / "approx_cone.v"
    approx_cone.write_text("""
    module axc_cone_0 (
        input wire [7:0] a,
        input wire [7:0] b,
        output wire [8:0] y
    );
        assign y = a + b;
    endmodule
    """)

    out_final = tmp_path / "final_top.v"
    reintegrator = Reintegrator(
        top_shell_path=top_shell,
        approx_cone_path=approx_cone,
        tech="NanGate15nm",
    )
    result = reintegrator.reintegrate(out_final_path=out_final, flatten=False)

    assert result["status"] == "SUCCESS"
    assert result["top_module"] == "top_shell"
    assert result["flattened"] is False
    assert out_final.exists()
    content = out_final.read_text()
    assert "top_shell" in content
    assert "axc_cone_0" in content


def test_reintegrator_flattened(tmp_path: Path):
    top_shell = tmp_path / "top_shell.v"
    top_shell.write_text("""
    module top_shell (
        input wire [7:0] a,
        input wire [7:0] b,
        output wire [8:0] y
    );
        axc_cone_0 inst_sub (
            .a(a),
            .b(b),
            .y(y)
        );
    endmodule
    """)

    approx_cone = tmp_path / "approx_cone.v"
    approx_cone.write_text("""
    module axc_cone_0 (
        input wire [7:0] a,
        input wire [7:0] b,
        output wire [8:0] y
    );
        assign y = a + b;
    endmodule
    """)

    out_final = tmp_path / "final_flattened.v"
    reintegrator = Reintegrator(
        top_shell_path=top_shell,
        approx_cone_path=approx_cone,
        tech="NanGate15nm",
    )
    result = reintegrator.reintegrate(out_final_path=out_final, flatten=True)

    assert result["status"] == "SUCCESS"
    assert result["flattened"] is True
    assert out_final.exists()
    content = out_final.read_text()
    assert "module top_shell" in content


def test_reintegrator_tech_resolution(tmp_path: Path):
    top_shell = tmp_path / "top_shell.v"
    top_shell.write_text("module top; endmodule")
    approx_cone = tmp_path / "approx_cone.v"
    approx_cone.write_text("module sub; endmodule")

    # Custom tech file
    dummy_tech = tmp_path / "custom_tech.v"
    dummy_tech.write_text("/* custom tech */")

    reint_custom = Reintegrator(
        top_shell_path=top_shell,
        approx_cone_path=approx_cone,
        tech="custom",
        tech_verilog_path=dummy_tech,
    )
    assert reint_custom.tech_v == dummy_tech.resolve()

    # Default tech fallback
    reint_default = Reintegrator(
        top_shell_path=top_shell,
        approx_cone_path=approx_cone,
        tech="NanGate15nm",
    )
    assert reint_default.tech_v == TECH_V_DEFAULT.resolve()
