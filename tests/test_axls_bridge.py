"""Unit tests for AxlsBridge module."""

from pathlib import Path
import pytest
from axsys.axls_bridge import AxlsBridge


def test_axls_bridge_init(tmp_path: Path):
    dummy_vlog = tmp_path / "dummy.v"
    dummy_vlog.write_text("module dummy; endmodule")

    bridge = AxlsBridge(
        cone_verilog_path=dummy_vlog,
        tech="NanGate15nm",
        samples=100,
        work_dir=tmp_path / "work",
    )
    assert bridge.cone_vlog == dummy_vlog.resolve()
    assert bridge.tech == "NanGate15nm"
    assert bridge.samples == 100


def test_axls_bridge_optimize_isolated(tmp_path: Path):
    cone_vlog = tmp_path / "simple_add.v"
    cone_vlog.write_text("""
    module simple_add (
        input wire [3:0] a,
        input wire [3:0] b,
        output wire [4:0] y
    );
        assign y = a + b;
    endmodule
    """)

    out_approx = tmp_path / "approx_out.v"
    bridge = AxlsBridge(
        cone_verilog_path=cone_vlog,
        tech="NanGate15nm",
        samples=50,
        work_dir=tmp_path / "work",
    )
    res = bridge.optimize(
        metric="med",
        bound=1.0,
        lsb_width=2,
        out_approx_path=out_approx,
        isolated=True,
    )

    assert res["status"] == "SUCCESS"
    assert out_approx.exists()
    assert "area_savings_percent" in res
    assert "pruned_nodes_count" in res
