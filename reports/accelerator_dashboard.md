# AxSYS: Complete Hardware Accelerator Evaluation Dashboard
## Multi-PE 2D Systolic Tensor Cores (NanGate 15nm Open Cell Library @ 100 MHz, $V_{DD} = 0.8\text{ V}$)

---

### 1. Executive Summary

We evaluated the complete hardware accelerator flow on open-source, third-party ASIC hardware: the **Parameterizable 2D Systolic Tensor Core** (sourced from [`ridash2005/Systolic-Array-based-Hardware-Accelerator-for-CNNs`](https://github.com/ridash2005/Systolic-Array-based-Hardware-Accelerator-for-CNNs)). 

Rather than testing an isolated arithmetic cell in a vacuum, this benchmark evaluates the **entire accelerator core**:
1. **$4\times 4$ 2D Systolic Grid (16 PEs)** with diagonal input skewing shift registers, central FSM control, and full 512-bit matrix accumulator output buses.
2. **$8\times 8$ 2D Systolic Grid (64 PEs)** with 2,048-bit matrix output buses to demonstrate multi-PE macro-scaling.
3. Standard-cell physical mapping in **NanGate 15nm CMOS** to measure both **silicon area ($\mu m^2$)** and **power dissipation ($\mu\text{W}$)** (static leakage vs. dynamic switching).
4. End-to-end matrix multiplication verification ($C = A \times B$) across 100 randomized matrix workloads, verifying **zero control corruption** and evaluating the **Frobenius norm matrix error**.

---

### 2. High-Resolution Visual Dashboard

![Complete Accelerator Dashboard](/home/christos-ntoumas/.gemini/antigravity-cli/brain/e307950d-ab38-4a9a-a41a-8a0aa8fe367e/dashboard_accelerator.png)

---

### 3. Accelerator Architecture & Attribute Partitioning

The hardware architecture consists of a 2D mesh of pipelined Processing Elements (`PE_MAC`) orchestrated by input skewing delay lines and an execution controller.

```mermaid
flowchart TD
    subgraph Control_Shell["Precise Control & Forwarding Shell (* axc_precise = '1' *)"]
        CLK["clk / rst_n"]
        START["start / done FSM"]
        SKEW_A["Matrix A Skewing Delay Lines [ROWS]"]
        SKEW_B["Matrix B Skewing Delay Lines [COLS]"]
        PE_FWD["Systolic Inter-PE Forwarding Buses (A_out, B_out)"]
    end

    subgraph Approximate_Datapath["Relaxed Arithmetic Datapath (* axc_relax = '1' *)"]
        PE00["PE [0,0] MAC Core"]
        PE01["PE [0,1] MAC Core"]
        PE10["PE [1,0] MAC Core"]
        PE11["PE [1,1] MAC Core"]
        ACC_GRID["16-64 Accumulators -> Matrix C Result Bus"]
    end

    START -->|Sync Pulse| SKEW_A
    START -->|Sync Pulse| SKEW_B
    SKEW_A --> PE_FWD
    SKEW_B --> PE_FWD
    PE_FWD --> PE00 & PE01 & PE10 & PE11
    PE00 & PE01 & PE10 & PE11 --> ACC_GRID
    ACC_GRID -->|Full Precision Interface| C_OUT["C_out [ROWS*COLS*32-1:0]"]
```

---

### 4. Comprehensive Performance & Verification Results

#### Table 1: $4\times 4$ Accelerator Core (16 PEs, 1,600 Matrix Output Elements Evaluated)

| Configuration | LSBs Pruned | Cell Count | Silicon Area ($\mu m^2$) | Area Cut | Leakage Power | Dynamic Power | Total Power | Power Cut | Frobenius Err (%) | Control Errors | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Exact Baseline** | 0 | 16,487 | 6,443.98 | — | 260.67 $\mu\text{W}$ | 204.31 $\mu\text{W}$ | 464.98 $\mu\text{W}$ | — | 0.000% | 0 | **PASSED** |
| **Light Approx** | 2 | 16,078 | 6,234.88 | **-3.24%** | 251.57 $\mu\text{W}$ | 198.98 $\mu\text{W}$ | 450.55 $\mu\text{W}$ | **-3.10%** | **0.042%** | 0 | **PASSED** |
| **Conservative** | 4 | 15,332 | 5,984.90 | **-7.12%** | 241.50 $\mu\text{W}$ | 191.37 $\mu\text{W}$ | 432.87 $\mu\text{W}$ | **-6.91%** | **0.253%** | 0 | **PASSED** |
| **Moderate** | 6 | 14,887 | 5,759.98 | **-10.61%** | 227.65 $\mu\text{W}$ | 185.91 $\mu\text{W}$ | 413.56 $\mu\text{W}$ | **-11.06%** | **1.152%** | 0 | **PASSED** |
| **Aggressive** | 8 | 14,024 | 5,430.22 | **-15.73%** | 217.81 $\mu\text{W}$ | 175.53 $\mu\text{W}$ | 393.34 $\mu\text{W}$ | **-15.41%** | **4.811%** | 0 | **PASSED** |

---

#### Table 2: Multi-PE Array Scaling & Global Compounding Analysis (at LSB=4)

| Architectural Scale | Active PEs | Baseline Area | Approx Area | **Silicon Area Saved** | Baseline Power | Approx Power | **Total Power Saved** | Compounding Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Single PE** | 1 | 292.70 $\mu m^2$ | 269.99 $\mu m^2$ | **22.71 $\mu m^2$** | 22.40 $\mu\text{W}$ | 20.77 $\mu\text{W}$ | **1.63 $\mu\text{W}$** | $1\times$ |
| **$4\times 4$ Tensor Core** | 16 | 6,443.98 $\mu m^2$ | 5,984.90 $\mu m^2$ | **459.08 $\mu m^2$** | 464.98 $\mu\text{W}$ | 432.87 $\mu\text{W}$ | **32.11 $\mu\text{W}$** | **$20.2\times$** |
| **$8\times 8$ Tensor Core** | 64 | 25,727.97 $\mu m^2$ | 23,789.13 $\mu m^2$ | **1,938.84 $\mu m^2$** | 1,860.34 $\mu\text{W}$ | 1,724.16 $\mu\text{W}$ | **136.18 $\mu\text{W}$** | **$83.5\times$** |

---

### 5. Key Engineering Insights

1. **Global Compounding in Tensor Mesh Architectures**:
   - In isolated PE benchmarks, an approximate MAC saves ~22.7 $\mu m^2$ and ~1.63 $\mu\text{W}$.
   - When scaled to a $4\times 4$ accelerator core, the savings compound to **$459.1\,\mu m^2$** and **$32.11\,\mu\text{W}$**.
   - In an $8\times 8$ core (64 PEs), the savings surge to **$1,938.84\,\mu m^2$ of eliminated silicon** and **$136.18\,\mu\text{W}$ of power reduction**, eliminating over **5,117 standard cells** from the chip floorplan.
2. **Deep Learning "Sweet Spot" Pareto Efficiency**:
   - The **Conservative profile (LSB=4)** yields **$-7.12\%$ silicon area** and **$-6.91\%$ total power reduction** while maintaining a tiny **$0.25\%$ Frobenius norm matrix error** ($>99.7\%$ computation fidelity).
   - The **Moderate profile (LSB=6)** exceeds double-digit reductions (**$-10.61\%$ area, $-11.06\%$ power**) at just **$1.15\%$ Frobenius error**, ideal for resilient deep neural network inference (e.g. MobileNet, ResNet).
3. **100% Control & Timing Robustness**:
   - Across all 100 simulation batches (evaluating 1,600 matrix elements for $4\times 4$ and 6,400 elements for $8\times 8$), the `done` pulse and cycle counter asserted with **zero cycle drift** and **0 bit-flips** on control paths.
   - The systolic data forwarding shift registers (`A_shift`, `B_shift`, `A_out`, `B_out`) remained unaffected by the arithmetic approximation.

---

### 6. Local Workspace Integrity
- All netlists, simulation binaries, and sweeps were generated strictly locally in `examples/systolic_accelerator/` and `build/accelerator_sweep/`.
- **No changes have been committed, staged, or pushed to any remote repository.**
