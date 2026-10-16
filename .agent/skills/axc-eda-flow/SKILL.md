---
name: axc-eda-flow
description: Build, synthesize, and verify attribute-driven approximate computing hardware flows from Verilog RTL to gate-level netlists and physical layout (GDSII). Use when the user asks to write or debug annotated Verilog with (* axc_relax *) or (* axc_precise *) attributes, write Pyosys RTLIL cone-extraction or relaxability inference passes, integrate with AxLS or BLASYS approximate logic synthesis, or configure OpenROAD/OpenLane 2 physical design and SDC timing relaxation for approximate circuits.
---
# axc-eda-flow

Implement an end-to-end open-source Approximate Logic Synthesis (ALS) flow using IEEE 1364/1800 Verilog attributes, Yosys/Pyosys RTLIL graph analysis, AxLS gate-level approximation, and OpenROAD physical implementation.

## When to Use

- Writing or annotating Verilog RTL with `(* axc_relax *)` and `(* axc_precise *)` attributes for approximate hardware design.
- Developing Pyosys scripts to traverse `RTLIL` netlists, perform Relaxability Inference Analysis, and isolate combinational subcircuits using `submod`.
- Bridging Yosys-extracted submodules into `AxLS` (Probabilistic Pruning, `InOuts` pruning, or Decision Tree synthesis) or `BLASYS`.
- Generating relaxed `.sdc` timing constraints and running post-approximation netlists through `iverilog` verification or OpenROAD / OpenLane 2 RTL-to-GDSII flows.

## Steps

### 1. Enforce Workspace Environment and Imports

Run all Python scripts and tests inside the project virtual environment (`./.venv/bin/python` and `./.venv/bin/pytest`) so `pyosys`, `numpy`, and `scikit-learn` resolve cleanly.

When interfacing with `AxLS`, inject `third_party/AxLS` into `sys.path` before importing because `AxLS` uses flat, non-packaged relative imports:

```python
import sys
from pathlib import Path

AXLS_DIR = Path(__file__).resolve().parent.parent / "third_party" / "AxLS"
sys.path.insert(0, str(AXLS_DIR))

from pyosys import libyosys as ys
```

### 2. Annotate Verilog RTL Using IEEE-Standard Attributes

Use standard Verilog `(* ... *)` attributes rather than custom keywords so the RTL remains 100% compatible with `yosys`, `iverilog`, and `verilator`.

Apply these attributes consistently:

- `(* axc_relax = "1" *)`: Marks an output port, wire, or register whose combinational fan-in cone is a candidate for approximation.
- `(* axc_metric = "MED", axc_bound = "0.02" *)`: Attaches the target error metric (`MED`, `MRED`, `WCE`, `ER`) and numeric threshold directly to the relaxed wire.
- `(* axc_lsb_width = 8 *)`: Optional bit-slice hint indicating how many least-significant bits of a multi-bit bus may be approximated.
- `(* axc_precise = "1" *)`: Marks control signals (FSM state registers, `valid`/`ready` handshakes, memory addresses, write enables) that must never be tainted by approximation.

Example annotated MAC Processing Element:

```verilog
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
```

### 3. Elaborate and Run Relaxability Inference in Pyosys

In Yosys `RTLIL`, all non-internal identifiers begin with a leading backslash (for example, `\axc_relax`, `\axc_precise`, `\submod`). Always elaborate behavioral blocks (`proc; opt_clean`) before inspecting cells, and avoid running destructive flattening or ABC passes before reading wire attributes so attribute metadata stays intact.

Follow this exact algorithm in `src/cone_extractor.py` to isolate safe combinational cones:

1. **Load and Elaborate RTL:**
   Run `read_verilog <file.v>; hierarchy -check -auto-top; proc; opt_expr; opt_clean` on a `ys.Design()` instance.
2. **Build Signal-to-Cell Adjacency Maps:**
   Iterate over `top_module.cells_.values()`. Classify sequential cells (`$dff`, `$adff`, `$sdff`, `$_DFF_*`, `$mem*`) as boundaries. For combinational cells, inspect cell port connections (`cell.connections()`) and use `cell.input(port_name)` and `cell.output(port_name)` to map each `RTLIL::SigBit` to its driving cell and sink cells.
3. **Backward Relaxed Cone Traversal:**
   Start from all wires carrying `\axc_relax` (optionally restricted to the lowest `axc_lsb_width` bits) and perform a backward Breadth-First Search (BFS) across combinational driving cells to find the candidate approximation set $C_{\text{relax}}$. Stop traversal at primary inputs and sequential cell outputs.
4. **Backward Taint Protection from Precise Signals:**
   Collect all wires carrying `\axc_precise`, plus all sequential state control inputs (`\EN`, `\RST`, `\ADDR`) and unannotated primary outputs. Perform a backward BFS from these protected signals to find every combinational cell in their Cone of Influence ($C_{\text{precise}}$).
5. **Compute Safe Submodule Cells and Partition via `submod`:**
   The safe-to-approximate cell set is $C_{\text{safe}} = C_{\text{relax}} \setminus C_{\text{precise}}$. Tag every cell in $C_{\text{safe}}$ with the `\submod` attribute (`cell.set_string_attribute(ys.IdString("\\submod"), "axc_cone_0")`) and run `ys.run_pass("submod; opt_clean", design)`. Yosys automatically extracts those cells into a new module named `axc_cone_0` and replaces them in the top module with a cell instance.

Template for tagging and extracting a cone in Pyosys:

```python
from pyosys import libyosys as ys

def extract_safe_cone(verilog_path: str, extracted_vlog: str, top_vlog: str):
    design = ys.Design()
    ys.run_pass(f"read_verilog {verilog_path}; hierarchy -check -auto-top; proc; opt_clean", design)
    top = design.top_module()

    relax_id = ys.IdString("\\axc_relax")
    precise_id = ys.IdString("\\axc_precise")
    submod_id = ys.IdString("\\submod")

    # After computing safe_cells = C_relax - C_precise via BFS:
    for cell in safe_cells:
        cell.set_string_attribute(submod_id, "axc_cone_0")

    ys.run_pass("submod; opt_clean", design)
    ys.run_pass(f"select -module axc_cone_0; write_verilog -selected {extracted_vlog}; select -clear", design)
    ys.run_pass(f"delete axc_cone_0; write_verilog {top_vlog}", design)
```

### 4. Approximate the Isolated Cone with AxLS

Feed `axc_cone_0.v` into `AxLS` along with a technology Liberty file (such as `NanGate15nm.lib` included in `third_party/AxLS` or `sky130_fd_sc_hd__tt_025C_1v80.lib`).

1. **Synthesize to Gate-Level Netlist:**
   Use `AxLS` or Yosys (`synth -top axc_cone_0; dfflibmap -liberty <lib>; abc -liberty <lib>; opt_clean; write_verilog axc_cone_0_syn.v`) to map the isolated cone to standard cells.
2. **Generate a Self-Checking Testbench:**
   Auto-generate an Icarus Verilog testbench (`tb_axc_cone_0.v`) that stimulates the isolated cone inputs (either with uniform random vectors or representative application activations captured from the parent testbench) and dumps switching activity (`.vcd` / `.saif`) and exact outputs.
3. **Run AxLS Approximation Transformations:**
   Apply one of the core `AxLS` transformation strategies until the parsed `axc_bound` error limit is reached:
   - **InOuts Pruning:** Prunes gates starting from the least-significant output paths.
   - **Probabilistic Pruning (`ProbPrun`):** Ranks internal gates by toggling probability from simulation and prunes low-activity/low-significance nodes.
   - **Decision Tree Replacement:** Trains a `scikit-learn` `DecisionTreeClassifier` on the input-output truth table of the cone, exports the reduced logic equations, and re-synthesizes them with Yosys.

### 5. Re-Integrate and Run Physical Implementation (OpenROAD / GDSII)

1. **Stitch Approximated Cone Back into Top Design:**
   Read the parent module (`top_shell.v`) and the approximated submodule (`axc_cone_0_approx.v`) back into Yosys:

   ```bash
   yosys -p "read_verilog top_shell.v axc_cone_0_approx.v; hierarchy -check -auto-top; flatten; opt_clean; write_verilog final_approx_top.v"
   ```

2. **Emit Attribute-Driven Relaxed SDC Constraints:**
   For paths driving `(* axc_relax *)` outputs, emit `.sdc` multicycle or relaxed delay constraints (`set_max_delay` on the least-significant approximate bits) so `OpenSTA` and OpenROAD's `Resizer` do not insert high-power buffers on paths where occasional LSB setup slack relaxation is acceptable.
3. **Evaluate in OpenLane 2 / OpenROAD:**
   Pass both the exact baseline netlist and `final_approx_top.v` through OpenROAD (`sky130hd` or `freepdk45`) to compare post-layout die area, gate count, critical path slack, and switching power (using VCD activity in `OpenSTA`).

### 6. Verify Every Transformation

Never consider an approximation pass complete without automated verification:

- Compile the exact top module and the approximated top module side-by-side in a miter/comparison testbench using `iverilog -g2012 -o sim.vvp tb_top.v exact_top.v final_approx_top.v` and execute `vvp sim.vvp`.
- Assert two properties in the testbench:
  1. **Zero Control Corruption:** Every `(* axc_precise *)` output (such as `valid_out`, `ready_out`, FSM state) matches the exact reference on 100% of clock cycles.
  2. **Bounded Datapath Error:** The measured error metric (`MED`, `MRED`, or `WCE`) on `(* axc_relax *)` outputs is less than or equal to the annotated `axc_bound`.

## Gotchas

- **Leading Backslashes in RTLIL:** Yosys stores Verilog identifier and attribute names with a leading backslash (`\axc_relax`, not `axc_relax`). Always prefix custom names with `\\` in Python strings when calling `ys.IdString("\\axc_relax")`.
- **Attribute Loss During Early Flattening:** Running `synth` or `abc` before inspecting attributes strips intermediate wire names and attributes. Always run your Pyosys attribute traversal and `submod` extraction right after `proc; opt_clean` (at the coarse-grain RTLIL level) before running gate-level mapping with `abc`.
- **Shared Logic Cones Between Precise and Relaxed Signals:** An adder or comparator might feed both a relaxed datapath output and a precise branch condition (`if (sum == 0)`). Never approximate a cell in $C_{\text{relax}}$ without first subtracting $C_{\text{precise}}$, or you will corrupt control flow.
- **AxLS Working Directory Expectations:** Several scripts in `third_party/AxLS` invoke `yosys`, `iverilog`, and `vvp` assuming relative paths to temporary files. Run `AxLS` functions from a clean temporary working directory or pass resolved absolute paths.