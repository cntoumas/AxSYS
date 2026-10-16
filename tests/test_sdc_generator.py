"""Unit tests for SDC timing constraint generator."""

import json
import subprocess
import sys
from pathlib import Path

from axsys.sdc_generator import SdcGenerator


def test_sdc_empty_relaxed_signals(tmp_path: Path) -> None:
    meta = {
        "top_module": "dummy_top",
        "relaxed_signals": [],
    }
    out_sdc = tmp_path / "dummy.sdc"
    gen = SdcGenerator(clk_port="clk", clk_period_ns=10.0, relaxation_factor=1.5, constraint_mode="max_delay")
    content = gen.generate_sdc(metadata=meta, out_sdc_path=out_sdc)

    assert out_sdc.exists()
    assert "create_clock -name clk -period 10.000 [get_ports clk]" in content
    assert "set_clock_uncertainty 0.05 [get_clocks clk]" in content
    assert "set_input_delay [expr {10.000 * 0.30}] -clock clk [all_inputs -no_clocks]" in content
    assert "set_output_delay [expr {10.000 * 0.30}] -clock clk [all_outputs]" in content
    assert "No (* axc_relax *) signals found" in content


def test_sdc_max_delay_multibit_and_single_bit(tmp_path: Path) -> None:
    meta = {
        "top_module": "mac_pe",
        "relaxed_signals": [
            {
                "wire": "acc_out",
                "width": 16,
                "lsb_width": 4,
                "metric": "MED",
                "bound": 0.05,
            },
            {
                "wire": "flag_out",
                "width": 1,
                "lsb_width": 1,
                "metric": "ER",
                "bound": 0.01,
            },
        ],
    }
    out_sdc = tmp_path / "mac_pe.sdc"
    gen = SdcGenerator(clk_port="sys_clk", clk_period_ns=5.0, relaxation_factor=2.0, constraint_mode="max_delay")
    content = gen.generate_sdc(metadata=meta, out_sdc_path=out_sdc)

    assert "create_clock -name sys_clk -period 5.000 [get_ports sys_clk]" in content
    # Relaxed delay = 5.0 * 2.0 = 10.000
    for bit in range(4):
        assert f"set_max_delay 10.000 -to [get_ports {{acc_out[{bit}]}}]" in content
    # Bits >= 4 must NOT be relaxed
    assert "set_max_delay 10.000 -to [get_ports {acc_out[4]}]" not in content

    # Single bit width=1 port formatting
    assert "set_max_delay 10.000 -to [get_ports {flag_out}]" in content


def test_sdc_multicycle_mode(tmp_path: Path) -> None:
    meta = {
        "top_module": "alu_approx",
        "relaxed_signals": [
            {
                "wire": "result",
                "width": 8,
                "lsb_width": 2,
                "metric": "WCE",
                "bound": 1.0,
            }
        ],
    }
    out_sdc = tmp_path / "multicycle.sdc"
    gen = SdcGenerator(clk_port="clk", clk_period_ns=8.0, constraint_mode="multicycle")
    content = gen.generate_sdc(metadata=meta, out_sdc_path=out_sdc)

    for bit in range(2):
        assert f"set_multicycle_path 2 -setup -to [get_ports {{result[{bit}]}}]" in content
        assert f"set_multicycle_path 1 -hold -to [get_ports {{result[{bit}]}}]" in content
    assert "set_multicycle_path 2 -setup -to [get_ports {result[2]}]" not in content


def test_sdc_cli_execution(tmp_path: Path) -> None:
    meta = {
        "top_module": "cli_test",
        "relaxed_signals": [
            {"wire": "data_out", "width": 8, "lsb_width": 3, "metric": "MED", "bound": 0.05}
        ],
    }
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    out_sdc = tmp_path / "cli_test.sdc"

    cmd = [
        sys.executable,
        "-m", "axsys.sdc_generator",
        "-m", str(meta_path),
        "-o", str(out_sdc),
        "--clk", "core_clk",
        "--period", "4.0",
        "--factor", "1.5",
        "--mode", "max_delay",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0
    assert out_sdc.exists()
    content = out_sdc.read_text(encoding="utf-8")
    assert "create_clock -name core_clk -period 4.000 [get_ports core_clk]" in content
    assert "set_max_delay 6.000 -to [get_ports {data_out[0]}]" in content
