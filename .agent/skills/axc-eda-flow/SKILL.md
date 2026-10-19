---
name: axc-eda-flow
description: Build, synthesize, and verify attribute-driven approximate computing hardware flows from Verilog RTL to gate-level netlists and physical layout (GDSII). Use when the user asks to write or debug annotated Verilog with (* axc_relax *) or (* axc_precise *) attributes, write Pyosys RTLIL cone-extraction or relaxability inference passes, integrate with AxLS or BLASYS approximate logic synthesis, or configure OpenROAD/OpenLane 2 physical design and SDC timing relaxation for approximate circuits.
---
# axc-eda-flow

Implement an end-to-end open-source Approximate Logic Synthesis (ALS) flow using IEEE 1364/1800 Verilog attributes, Yosys/Pyosys RTLIL graph analysis, AxLS gate-level approximation, Liberty standard-cell power estimation, and OpenROAD physical implementation.

## When to Use

- Writing or annotating Verilog RTL with `(* axc_relax *)` and `(* axc_precise *)` attributes for approximate hardware design.
- Determining and tuning error bounds (`axc_bound`, `axc_metric`, `axc_lsb_width`) for target application domains.
- Developing Pyosys scripts to traverse `RTLIL` netlists, perform Relaxability Inference Analysis, and isolate combinational subcircuits using `submod`.
- Bridging Yosys-extracted submodules into `AxLS` (Probabilistic Pruning, `InOuts` pruning, or Decision Tree synthesis) or `BLASYS`.
- Evaluating gate-level standard-cell power and area trade-offs using Liberty `.lib` files.
- Generating relaxed `.sdc` timing constraints and running post-approximation netlists through automated dual-miter `iverilog` verification or OpenROAD / OpenLane 2 RTL-to-GDSII flows.

---

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

---

### 2. Annotate Verilog RTL Using IEEE-Standard Attributes

Use standard Verilog `(* ... *)` attributes rather than custom keywords so the RTL remains 100% compatible with `yosys`, `iverilog`, and `verilator`.

Apply these attributes consistently:

- `(* axc_relax = "1" *)`: Marks an output port, wire, or register whose combinational fan-in cone is a candidate for approximation.
- `(* axc_metric = "MED" *)`: Attaches the target error metric:
  - `MED` (Mean Error Distance): Average absolute difference in raw integer/code units ($\frac{1}{N} \sum |y_{\text{exact}} - y_{\text{approx}}|$).
  - `WCE` (Worst-Case Error): Maximum absolute difference across all cycles ($\max |y_{\text{exact}} - y_{\text{approx}}|$).
  - `MRED` (Mean Relative Error Distance): Average relative percentage/fraction ($\frac{1}{N} \sum \frac{|y_{\text{exact}} - y_{\text{approx}}|}{|y_{\text{exact}}|}$).
  - `ER` (Error Rate): Percentage of cycles where $y_{\text{approx}} \neq y_{\text{exact}}$.
- `(* axc_bound = "16.0" *)`: The maximum allowable numeric error threshold for the chosen metric.
- `(* axc_lsb_width = 5 *)`: Explicit bit-slice restriction indicating how many least-significant bits of a multi-bit bus are relaxed. The upper bits remain 100% exact and protected.
- `(* axc_precise = "1" *)`: Marks control signals (FSM state registers, `valid`/`ready` handshakes, memory addresses, write enables) that must never be tainted by approximation.

#### How to Calculate and Choose `axc_bound`

1. **Understand the Units:**
   - For `MED` and `WCE`: The bound has the **exact same units as the output wire** (e.g. raw integer counts, millivolts, brightness levels).
   - For `MRED`: The bound is a **decimal fraction** representing relative error (e.g., `0.02` for 2% error).

2. **Calculation Method A (Percentage of Nominal Signal):**
   $$\text{Bound (MED)} = \text{Typical Output Value} \times \text{Acceptable Error Fraction}$$
   - *Example (8-bit Image Grayscale, nominal ~128, 3% tolerance):* $\text{Bound} = 128 \times 0.03 \approx 4.0 \text{ to } 8.0$.
   - *Example (16-bit Robotics Coordinate, nominal ~10,000, 0.15% tolerance):* $\text{Bound} = 10,000 \times 0.0015 = 15.0 \rightarrow \text{Bound} = 16.0$.

3. **Calculation Method B (Bit-Weight Heuristic):**
   When pruning the lower $K$ least-significant bits (`axc_lsb_width = K`):
   $$\text{Max Error (WCE)} = 2^K - 1 \qquad \text{Average Error (MED)} \approx 2^{K-1}$$

   | Relaxed LSBs ($K$) | Target `axc_bound` (`MED`) | Application Fit |
   | :---: | :---: | :--- |
   | **3 bits** (`lsb_width = 3`) | `4.0` | High-fidelity scientific / coordinate calculations |
   | **4 bits** (`lsb_width = 4`) | `8.0` | Standard for Computer Vision (Sobel) and Quantized ML (FFNN) |
   | **5 bits** (`lsb_width = 5`) | `16.0` | Digital Signal Processing (FIR), Audio, Transforms (IDCT) |
   | **6 bits** (`lsb_width = 6`) | `32.0` | Aggressive pruning for highly noise-tolerant sensors |

> [!WARNING]
> **Scalar Bound vs. Bus Width:** `axc_bound = "16.0"` does NOT mean relaxing 16 bit positions! On a 16-bit signal, relaxing 16 bits would corrupt 100% of the word including the sign bit. Set `axc_lsb_width = 4` (only the lower 4 bit positions are relaxed; the upper 12 bits remain exact) and `axc_bound = "16.0"`.

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
    (* axc_relax = "1", axc_metric = "MED", axc_bound = "16.0", axc_lsb_width = 5 *)
    output wire signed [16:0] y
);
    assign y = (a * b) + c;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) valid_out <= 1'b0;
        else        valid_out <= valid_in;
    end
endmodule
```

---

### 3. Elaborate and Run Relaxability Inference in Pyosys

In Yosys `RTLIL`, all non-internal identifiers begin with a leading backslash (`\axc_relax`, `\axc_precise`, `\submod`). Always elaborate behavioral blocks (`proc; opt_clean`) before inspecting cells, and avoid running destructive flattening or ABC passes before reading wire attributes so attribute metadata stays intact.

Follow this exact algorithm in `axsys/cone_extractor.py` to isolate safe combinational cones:

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

---

### 4. Approximate the Isolated Cone with AxLS

Feed `axc_cone_0.v` into `AxLS` along with a technology Liberty file (`NanGate15nm.lib` or `sky130_fd_sc_hd__tt_025C_1v80.lib`).

1. **Synthesize Cone to Gate-Level Netlist:**
   Use Yosys to map the isolated cone to target standard cells:
   ```bash
   synth -top axc_cone_0; dfflibmap -liberty <lib>; abc -liberty <lib>; opt_clean; write_verilog axc_cone_0_syn.v
   ```
2. **Generate Stimulus Vectors & Self-Checking Testbench:**
   Auto-generate an Icarus Verilog testbench (`tb_axc_cone_0.v`) that stimulates the isolated cone inputs with representative application vectors and dumps exact golden outputs.
3. **Run AxLS Approximation Transformations:**
   Iteratively evaluate candidate logic simplifications (gate deletions, constant-0/1 replacements, buffer feedthroughs):
   - Measure candidate error on the stimulus set.
   - If `candidate_error <= bound`: accept transformation.
   - If `candidate_error > bound`: reject and backtrack.

---

### 5. Re-Integrate, Generate Constraints, and Estimate Power

1. **Stitch Approximated Cone Back into Top Design:**
   Read the parent module (`top_shell.v`) and the approximated submodule (`axc_cone_0_approx.v`) back into Yosys:
   ```bash
   yosys -p "read_verilog top_shell.v axc_cone_0_approx.v; hierarchy -check -auto-top; flatten; opt_clean; write_verilog final_approx_top.v"
   ```
   > [!IMPORTANT]
   > When exporting mapped Verilog that will be simulated with standard-cell libraries (such as `NanGate15nm.v`), use `select <top_module>; write_verilog -selected final_approx_top.v` so standard-cell macro definitions are not duplicated into the output netlist.

2. **Emit Attribute-Driven Relaxed SDC Constraints:**
   For paths driving `(* axc_relax *)` outputs, emit relaxed `.sdc` timing constraints using `axsys.sdc_generator.SDCGenerator` (`set_max_delay` or multicycle exceptions on relaxed bitlines) to reduce buffer insertion and dynamic switching power during place-and-route.

3. **Fast Pre-Layout Power & Area Estimation:**
   Use `axsys.power_estimator.PowerEstimator` to compute cell area, static leakage, and dynamic switching power directly from the Liberty `.lib` without needing a full physical design run:
   ```python
   from axsys.power_estimator import PowerEstimator
   estimator = PowerEstimator("third_party/AxLS/templates/NanGate15nm.lib")
   report = estimator.evaluate_netlist("final_approx_top.v", clock_freq_mhz=200.0, supply_voltage=0.8)
   # Returns: cell_count, cell_area_um2, leakage_power_uw, dynamic_power_uw, total_power_uw
   ```

4. **Physical Implementation (OpenROAD / OpenLane 2):**
   Pass both baseline and `final_approx_top.v` with relaxed SDC constraints into OpenROAD (`sky130hd` or `freepdk45`) for post-layout GDSII die area, congestion, and timing closure.

---

### 6. Verify Every Transformation with Automated Dual-Miter

Never consider an approximation pass complete without automated cycle-accurate verification using `axsys.verifier.Verifier`:

```python
from axsys.verifier import Verifier
verifier = Verifier(liberty_file="third_party/AxLS/templates/NanGate15nm.lib")
result = verifier.verify(
    exact_rtl_path="fir.v",
    approx_netlist_path="final_approx_top.v",
    top_module="fir",
    relaxed_signals=[{"wire": "y_out", "metric": "MED", "bound": 16.0}],
    num_cycles=500
)
```

The dual-miter co-simulation enforces two mandatory invariants:
1. **Zero Control Corruption:** Every `(* axc_precise *)` signal (`valid_out`, FSM states, registers) must have **0 bit errors (100% exact match)**. Any mismatch reports `CONTROL_CORRUPTION_DETECTED` and fails sign-off.
2. **Bounded Datapath Error:** The measured error metric (`MED`, `WCE`, or `MRED`) must satisfy $\le \text{bound}$.

The verifier extracts 6 formal metrics:
- **MED** (Mean Error Distance)
- **WCE** (Worst-Case Error)
- **ER** (Error Rate percentage)
- **MSED** (Mean Squared Error)
- **MRED** (Mean Relative Error Distance)
- **SQNR** (Signal-to-Quantization-Noise Ratio in dB: $10 \log_{10}(1 / \text{MSED})$)

---

### 7. Official Benchmark Standards (AxBench Suite)

When evaluating or publishing ALS flows, use the canonical 5 AxBench circuits:

| Circuit ID | Domain | Top Module & Function | Typical Bus Width | Recommended `axc_lsb_width` | Recommended Bound (`MED`) | Target Application Criteria |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **`fir`** | Digital Signal Processing | 4-Tap Symmetric Filter | 18-bit signed | 5 bits | `16.0` | Audio SNR $\ge 20\text{ dB}$, MRED $< 5\%$ |
| **`sobel`** | Computer Vision | 3x3 Gradient Kernel | 8-bit unsigned | 4 bits | `8.0` | Grayscale luminance error $< 4\%$ (imperceptible) |
| **`inversek2j`** | Robotics / Motion Control | 2-DOF Arm Kinematics | 16-bit unsigned | 4 bits | `16.0` | Angle error $< 0.2\%$ (below mechanical backlash) |
| **`ffnn`** | Machine Learning / Edge AI | 4-Input Perceptron + ReLU | 16-bit unsigned | 4 bits | `8.0` | Top-1 inference classification drop $< 0.2\%$ |
| **`idct`** | Multimedia / Video Codec | 1D Inverse DCT Core | 16-bit signed | 4 bits | `16.0` | Arithmetic error below lossy JPEG $Q$-noise |

---

## Gotchas

- **Icarus Verilog `-DPRIMITIVES` Macro with NanGate 15nm:** `NanGate15nm.v` wraps sequential primitives (`DFFRNQ_X1`, etc.) inside `` `ifdef PRIMITIVES ``. When compiling gate-level netlists with `iverilog`, **always pass `-DPRIMITIVES`**:
  ```bash
  iverilog -g2012 -DPRIMITIVES -o sim.vvp tb_miter.v exact_top.v final_approx_top.v NanGate15nm.v
  ```
- **Duplicate Module Definitions in Gate-Level Verilog:** If Yosys re-exports standard-cell macro definitions, `iverilog` fails with duplicate module errors. Always use `select <top_module>; select -add <submod>; write_verilog -selected ...` to keep netlists clean.
- **Leading Backslashes in RTLIL:** Yosys stores Verilog identifier and attribute names with a leading backslash (`\axc_relax`, not `axc_relax`). Always prefix custom names with `\\` in Python strings when calling `ys.IdString("\\axc_relax")`.
- **Attribute Loss During Early Flattening:** Running `synth` or `abc` before inspecting attributes strips intermediate wire names and attributes. Always run your Pyosys attribute traversal and `submod` extraction right after `proc; opt_clean` (at coarse-grain RTLIL level) before running gate-level mapping with `abc`.
- **Shared Logic Cones Between Precise and Relaxed Signals:** An adder or comparator might feed both a relaxed datapath output and a precise branch condition (`if (sum == 0)`). Never approximate a cell in $C_{\text{relax}}$ without first subtracting $C_{\text{precise}}$ ($C_{\text{safe}} = C_{\text{relax}} \setminus C_{\text{precise}}$), or you will corrupt control flow.
- **AxLS Working Directory Expectations:** Several scripts in `third_party/AxLS` invoke `yosys`, `iverilog`, and `vvp` assuming relative paths to temporary files. Run `AxLS` functions from a clean temporary working directory or pass resolved absolute paths.