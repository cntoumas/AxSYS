# AxSYS

> **Attribute-Driven Approximate Logic Synthesis & Verification Framework**

AxSYS is an automated, end-to-end EDA toolchain that extracts, approximates, reintegrates, and formally verifies combinational logic cones directly from standard Verilog RTL using lightweight Verilog-2001 attributes.

```mermaid
flowchart TD
    subgraph S1["1. RTL Analysis & Extraction"]
        RTL["Input Verilog RTL<br/><code>(* axc_relax *)</code> / <code>(* axc_precise *)</code>"] --> CE["Pyosys RTLIL Cone Extractor"]
        CE --> Taint{"Taint Protection<br/>(Fan-in Isolation)"}
        Taint -->|Isolate Safe Datapath| Cone["Extracted Cone<br/><code>extracted_cone.v</code>"]
        Taint -->|Preserve Control Logic| Shell["Top Shell Wrapper<br/><code>top_shell.v</code>"]
    end

    subgraph S2["2. Approximate Logic Synthesis"]
        Cone --> AxLS["AxLS Pruning Engine<br/>(Subprocess Isolation)"]
        AxLS --> ApproxCone["Pruned Gate Netlist<br/><code>approx_cone.v</code>"]
    end

    subgraph S3["3. Reintegration"]
        Shell --> Reint["Hierarchical Reintegrator"]
        ApproxCone --> Reint
        Reint --> FullTop["Final Approximate Top<br/><code>final_approx_top.v</code>"]
    end

    subgraph S4["4. Timing Constraints"]
        FullTop --> SDC["SDC Generator"]
        SDC --> SDCFile["Relaxed Constraints<br/><code>final_approx_top.sdc</code>"]
    end

    subgraph S5["5. Automated Verification"]
        FullTop --> Miter["Miter Verification Harness"]
        RTL --> Miter
        Miter --> Sim["Icarus Verilog Simulation"]
        Sim --> Verdict{"Dual Verdict:<br/>1. Control Integrity (0 errors)<br/>2. Error <= Specified Bound"}
    end

    subgraph S6["6. Power Dissipation Estimation"]
        FullTop --> PE["Liberty (.lib) Power Estimator"]
        PE --> PowerReport["Static Leakage + Dynamic Switching<br/>Power & Area Report"]
    end

    style RTL fill:#1e40af,color:#fff
    style Taint fill:#d97706,color:#fff
    style FullTop fill:#047857,color:#fff
    style Verdict fill:#6d28d9,color:#fff
    style PowerReport fill:#b45309,color:#fff
```

---

## Key Features

- **Zero RTL Rewrites**: Keep your RTL untouched. Mark relaxable arithmetic outputs with `(* axc_relax *)` and control signals with `(* axc_precise *)`.
- **Hardware Taint Protection**: Disjoint Set Union (DSU) wire aliasing and backward BFS fan-in tracing guarantee that logic feeding critical control paths is never approximated ($C_{\text{safe}} = C_{\text{relax}} \setminus C_{\text{precise}}$).
- **Process Isolation**: Spawns AxLS approximate logic synthesis inside isolated worker subprocesses with timeout protection, avoiding global working directory pollution.
- **Automated Netlist Surgery**: Yosys RTLIL-level partitioning cleanly separates datapath cones into submodules and restitches synthesized gate netlists back into the top-level shell with dynamic technology library propagation.
- **Timing Constraint Relaxation**: Automatically generates Synopsys Design Constraints (`.sdc`) with relaxed max-delay or multi-cycle paths on approximate outputs for downstream physical design.
- **Self-Verifying Dual Miter**: Generates side-by-side miter testbenches to verify zero control corruption and validate Mean Error Distance (MED), Worst-Case Error (WCE), Error Rate (ER), Mean Squared Error (MSED), or Mean Relative Error (MRED) under cycle-accurate simulation with signed arithmetic support.
- **Power & Energy Modeling**: Cycle-accurate standard-cell static leakage and dynamic switching power estimation directly from technology Liberty (`.lib`) models.
- **Multi-Platform Support**: Evaluated across ASIC standard-cell libraries (NanGate 15nm) and FPGA soft-logic targets (Xilinx 7-Series Artix-7).

---

## RTL Attribute Specification

AxSYS parses standard Verilog-2001 attributes directly via Yosys frontends:

```verilog
module mac_pe (
    input  wire        clk,
    input  wire        rst_n,

    // Precise control paths — protected from pruning
    (* axc_precise = "1" *) input  wire valid_in,
    (* axc_precise = "1" *) output reg  valid_out,

    // Exact datapath inputs
    input  wire signed [7:0] a,
    input  wire signed [7:0] b,
    input  wire signed [15:0] c,

    // Relaxed datapath output with target error metric and bound
    (* axc_relax = "1", axc_metric = "MED", axc_bound = "0.05", axc_lsb_width = 8 *)
    output wire signed [16:0] y
);
    assign y = (a * b) + c;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) valid_out <= 1'b0;
        else        valid_out <= valid_in;
    end
endmodule
```

### Attribute Reference

| Attribute | Accepted Values | Purpose |
|---|---|---|
| `(* axc_relax = "1" *)` | `"1"` | Identifies the target signal for backward cone extraction and approximate pruning. |
| `(* axc_precise = "1" *)` | `"1"` | Strict protection flag. Logic feeding these signals is excluded from the approximate cone. |
| `axc_metric` | `"MED"`, `"WCE"`, `"ER"`, `"MSED"`, `"MRED"` | Optimization error target metric. |
| `axc_bound` | Numeric string (e.g. `"0.05"`, `"4.0"`) | Maximum error threshold allowed during pruning. |
| `axc_lsb_width` | Integer string (e.g. `"8"`) | *(Optional)* Restricts heuristic node pruning to the $N$ least significant bits. |

---

## Prerequisites & Installation

### System Dependencies

- **Linux** (x86_64)
- **Python 3.10+**
- **Yosys** compiled with `pyosys` Python bindings
- **Icarus Verilog** (`iverilog` & `vvp`)

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y iverilog yosys
```

### Environment Setup

```bash
git clone --recursive <repository-url>
cd AxSYS

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Usage

### Command Line Interface (CLI)

AxSYS installs four command-line executables:

#### 1. Full Pipeline Orchestrator (`axsys`)

```bash
axsys \
    --input rtl/design.v \
    --output-dir build/design_run \
    --tech NanGate15nm \
    --clk-period 5.0 \
    --samples 500 \
    --verify-cycles 500
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `-i`, `--input` | Path | *Required* | Path to attribute-annotated input Verilog RTL |
| `-o`, `--output-dir` | Path | `build/axc_output` | Output directory for all generated netlists and reports |
| `-t`, `--tech` | String | `NanGate15nm` | Target standard-cell library (`NanGate15nm`, etc.) |
| `--clk`, `--clk-port` | String | `clk` | Clock port name |
| `--period`, `--clk-period` | Float | `10.0` | Clock period in nanoseconds (for SDC generation) |
| `-s`, `--samples` | Integer | `300` | Number of simulation vectors for AxLS pruning |
| `-n`, `--verify-cycles` | Integer | `300` | Number of cycles to run in automated miter verification |
| `-v`, `--verbose` | Flag | `False` | Enable debug logging |

#### 2. Standalone Cone Extractor (`axsys-cone`)

```bash
axsys-cone -i rtl/design.v --out-submod extracted_cone.v --out-top top_shell.v --out-meta cone_meta.json
```

#### 3. Standalone SDC Generator (`axsys-sdc`)

```bash
axsys-sdc -m cone_meta.json -o final_approx_top.sdc --period 10.0 --mode max_delay
```

#### 4. Standalone Miter Verifier (`axsys-verify`)

```bash
axsys-verify --exact rtl/design.v --approx final_approx_top.v --meta cone_meta.json --tech NanGate15nm -n 500
```

---

### Python API

```python
from pathlib import Path
from axsys import AxcFlow

flow = AxcFlow(
    input_verilog=Path("rtl/design.v"),
    output_dir=Path("build/design_run"),
    tech="NanGate15nm",
    clk_port="clk",
    clk_period_ns=5.0,
    sim_samples=300,
    verify_cycles=500,
)

summary = flow.run()

if summary["flow_status"] == "SUCCESS":
    print("Synthesis & Verification Succeeded!")
    print(f"Area Savings: {summary['approximation']['area_savings_percent']:.2f}%")
    print(f"Nodes Pruned: {summary['approximation']['pruned_nodes']}")
    print(f"Control Integrity: {summary['verification']['control_integrity']}")
    if "power" in summary:
        print(f"Total Power: {summary['power']['total_power_uw']:.3f} uW "
              f"(Leakage: {summary['power']['leakage_power_uw']:.3f} uW, "
              f"Dynamic: {summary['power']['dynamic_power_uw']:.3f} uW)")
```

---

## Output Structure

Upon completion, the target output directory contains:

```
build/design_run/
├── cone_meta.json          # Machine-readable cone metadata and extraction report
├── extracted_cone.v        # Pure combinational RTL logic isolated from datapath
├── top_shell.v             # Golden top wrapper with submod instance
├── approx_cone.v           # Synthesized and pruned gate-level netlist
├── final_approx_top.v      # Fully reintegrated, simulatable top-level netlist
├── final_approx_top.sdc    # Generated timing constraints with relaxed output paths
└── flow_summary.json       # End-to-end execution summary (area, power, verification metrics)
```

---

## Examples & Benchmarks

The repository includes open-source accelerator benchmarks and validation suites in `examples/`:

- **MAC Processing Element** (`examples/mac/`): Minimal signed multiply-accumulate unit for fast end-to-end sanity tests.
- **Multi-Cone Sobel Operator** (`examples/sobel/`): 3x3 image convolution engine with 3 parallel approximation cones (`gx_abs`, `gy_abs`, `sobel_out`) and Pareto tradeoff sweeps.
- **Sequential INT8 Systolic PE** (`examples/systolic_pe/`): Deep learning processing element with strict control protection (`valid_out`, `a_out`, `b_out`) and up to 18.6% power savings.
- **2D Systolic Tensor Cores** (`examples/systolic_accelerator/`): Scaled $4\times 4$ and $8\times 8$ matrix multiplication cores evaluated on:
  - **NanGate 15nm ASIC**: Up to $1,938\,\mu m^2$ area and $15.4\%$ power reduction.
  - **Xilinx Artix-7 FPGA**: Soft-logic LUT/FF dead-code pruning, carry chain reduction, and DSP slice pressure relief.

---

## Testing

Run the automated test suite with pytest:

```bash
pytest -v
```

---

## Repository Architecture

```
.
├── axsys/
│   ├── __init__.py           # Package exports
│   ├── flow.py               # Top-level pipeline orchestrator & CLI
│   ├── cone_extractor.py     # RTLIL cone extraction, DSU aliasing & taint protection
│   ├── axls_bridge.py        # Subprocess-isolated bridge to AxLS pruning
│   ├── reintegrator.py       # Hierarchical netlist re-stitching
│   ├── sdc_generator.py      # SDC timing constraint generator
│   ├── verifier.py           # Dual-miter automated testbench harness
│   └── power_estimator.py    # Liberty (.lib) static leakage & dynamic power model
├── examples/
│   ├── mac/                  # Single MAC processing element
│   ├── sobel/                # Multi-cone Sobel operator
│   ├── systolic_pe/          # INT8 Systolic PE power/area sweep
│   └── systolic_accelerator/ # 4x4 and 8x8 2D systolic tensor arrays (ASIC + FPGA)
├── reports/                  # Evaluation dashboards, visual plots, and status audits
├── tests/
│   ├── conftest.py
│   ├── test_cone_extractor.py
│   ├── test_sdc_generator.py
│   ├── test_power_estimator.py
│   ├── test_reintegrator.py
│   ├── test_verifier.py
│   └── test_flow.py
├── third_party/
│   └── AxLS/                 # Approximate Logic Synthesis engine
├── pyproject.toml            # PEP 621 package and build specification
├── requirements.txt
├── LICENSE                   # MIT License
└── README.md
```

---

## License

This project is licensed under the MIT License. See [LICENSE](file:///home/christos-ntoumas/AxSYS/LICENSE) for details.
