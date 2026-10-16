"""End-to-End Flow Integration Tests."""

from pathlib import Path
from axsys.flow import AxcFlow


def test_full_pipeline_mac_pe(tmp_path: Path):
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
            (* axc_relax = "1", axc_metric = "MED", axc_bound = "10.0", axc_lsb_width = 8 *)
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
    flow = AxcFlow(
        input_verilog=rtl_path,
        output_dir=tmp_path / "mac_pe_out",
        tech="NanGate15nm",
        clk_port="clk",
        clk_period_ns=5.0,
        sim_samples=100,
        verify_cycles=100,
    )
    result = flow.run()

    assert result["flow_status"] in ("SUCCESS", "VERIFICATION_FAILED")
    assert result["top_module"] == "mac_pe"
    assert result["extracted_safe_cells"] == 2
    assert result["verification"]["control_integrity"] == "PASSED"
    assert result["verification"]["control_errors"] == 0

    # Check generated files
    files = result["generated_files"]
    assert Path(files["top_shell"]).exists()
    assert Path(files["extracted_cone"]).exists()
    assert Path(files["approx_cone"]).exists()
    assert Path(files["final_approx_top"]).exists()
    assert Path(files["sdc_constraints"]).exists()
    assert Path(files["metadata"]).exists()
