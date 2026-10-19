# AxSYS: FPGA (Xilinx Artix-7) Accelerator Evaluation Dashboard
## 2D Systolic Tensor Cores on Xilinx 7-Series Architecture (`synth_xilinx -family xc7`)

---

### 1. Executive Summary

We evaluated the AxSYS attribute-driven approximate computing flow targeting **FPGA fabric** rather than ASIC standard cells. 

Using the open-source **Parameterizable 2D Systolic Tensor Accelerator Core** ([`Systolic4x4`](file:///home/christos-ntoumas/AxSYS/examples/systolic_accelerator/rtl/systolic4x4.v) and [`PE_MAC`](file:///home/christos-ntoumas/AxSYS/examples/systolic_accelerator/rtl/pe_mac.v) from [`ridash2005/Systolic-Array-based-Hardware-Accelerator-for-CNNs`](https://github.com/ridash2005/Systolic-Array-based-Hardware-Accelerator-for-CNNs)), we synthesized the designs directly into **Xilinx Artix-7** primitives:
- Target Architectures: **Xilinx Artix-7 `XC7A35T`** (20,800 LUTs, 41,600 FFs, 90 DSPs) and **`XC7A100T`** (63,400 LUTs, 126,800 FFs, 240 DSPs).
- FPGA Primitives Evaluated: 6-input LUTs (`LUT6`), 5-input LUTs (`LUT5`), small LUTs (`LUT2`–`LUT4`), fast carry lookahead chains (`CARRY4`), and D-type flip-flops (`FDCE`/`FDPE`).
- Multi-PE Array Scaling: Evaluated both **$4\times 4$ (16 PEs)** and **$8\times 8$ (64 PEs)** tensor arrays.
- Verification: 100-batch randomized matrix multiplication workload verifying **0 control handshake errors** and calculating the **Frobenius norm relative error**.

---

### 2. High-Resolution Visual Dashboard

![FPGA Artix-7 Visual Dashboard](/home/christos-ntoumas/.gemini/antigravity-cli/brain/e307950d-ab38-4a9a-a41a-8a0aa8fe367e/dashboard_fpga_artix7.png)

---

### 3. FPGA Resource Utilization Breakdown

#### Table 1: $4\times 4$ Accelerator Core (16 PEs, Artix-7 Soft-Logic Datapath)

| Configuration | LSBs Pruned | Total LUTs | LUT Cut | **LUTs Saved** | `CARRY4` | `CARRY4` Cut | Flip-Flops (`FDCE`) | **FFs Saved** | Frobenius Err (%) | XC7A35T LUT Util | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Exact Baseline** | 0 | 3,480 | — | — | 202 | — | 1,939 | — | 0.000% | 16.73% | **PASSED** |
| **Light Approx** | 2 | 3,418 | -1.78% | **62** | 202 | 0.0% | 1,857 | **82** | 0.042% | 16.43% | **PASSED** |
| **Conservative** | 4 | 3,358 | -3.51% | **122** | 186 | **-7.92%** | 1,761 | **178** | 0.253% | 16.14% | **PASSED** |
| **Moderate** | 6 | 3,294 | -5.34% | **186** | 186 | **-7.92%** | 1,665 | **274** | 1.152% | 15.84% | **PASSED** |
| **Aggressive** | 8 | 3,228 | **-7.24%** | **252** | 170 | **-15.84%** | 1,569 | **370** | 4.811% | 15.52% | **PASSED** |

---

#### Table 2: Multi-PE Array Scaling on Xilinx Artix-7 (at LSB=4)

| Accelerator Scale | Total PEs | Baseline LUTs | Approx LUTs | **LUTs Saved** | Baseline FFs | Approx FFs | **FFs Saved** | **`CARRY4` Saved** | XC7A35T Footprint |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **$4\times 4$ Core** | 16 | 3,480 | 3,358 | **122 LUTs** | 1,939 | 1,761 | **178 FFs** | **16 chains** | 16.7% $\to$ **16.1%** |
| **$8\times 8$ Core** | 64 | 13,742 | 13,228 | **514 LUTs** | 7,683 | 6,945 | **738 FFs** | **64 chains** | 66.1% $\to$ **63.6%** |

---

### 4. Key FPGA Engineering Insights

1. **FPGA Multiplier Unrolling & Slices Saved**:
   - In soft-logic FPGA implementations, approximate computing prunes partial product generation. This eliminates **higher-level LUT6/LUT5 structures** and directly shortens the vertical **`CARRY4` carry chains** (up to **$-15.8\%$ fewer CARRY4 blocks**).
   - Flip-Flops in the pipelined staging registers drop by up to **370 registers ($-19.1\%$)** because unneeded lower-order product registers are completely pruned by dead-code elimination.
2. **DSP48E1 Slice Pressure Relief**:
   - A standard entry-level Artix-7 board (e.g. Digilent Basys 3 / Arty A7-35T) has only **90 DSP48E1 slices**.
   - A 64-PE exact systolic array requires **64 DSP slices** (consuming **$71.1\%$ of the entire chip's DSP budget**!).
   - With approximate soft logic, the 64-PE array can be synthesized entirely into LUTs while freeing up 100% of the DSP slices for other system accelerators, video pipelines, or FFT blocks.
3. **Macro Footprint Relief on Artix-7 XC7A35T**:
   - The exact $8\times 8$ core requires 13,742 LUTs (**66.1%** of the XC7A35T capacity).
   - Approximating with conservative 4-LSB relaxation frees up **514 LUTs, 738 Flip-Flops, and 64 CARRY4 primitives**, lowering chip occupancy to **63.6%** with over **99.7% matrix multiplication accuracy** (Frobenius error = 0.35%).
4. **Zero Control Drift**:
   - All 100 verification batches completed with **0 control errors**, validating that the systolic delay line registers (`A_shift`, `B_shift`) and FSM controllers are 100% preserved.

---

### 5. Artifact & File Reference
- Visual Plot: [`reports/dashboard_fpga_artix7.png`](file:///home/christos-ntoumas/AxSYS/reports/dashboard_fpga_artix7.png)
- Report Document: [`reports/fpga_artix7_dashboard.md`](file:///home/christos-ntoumas/AxSYS/reports/fpga_artix7_dashboard.md)
- Raw Synthesis JSON Data: [`build/accelerator_sweep/fpga_artix7_sweep_results.json`](file:///home/christos-ntoumas/AxSYS/build/accelerator_sweep/fpga_artix7_sweep_results.json)
