# AxBench Benchmark Report: Sobel Filter (`sobel`)

> **Application Domain:** Computer Vision / Image Processing  
> **Target Error Bound:** MED $\le 8.0$ (LSB Width = 4)  
> **Technology:** NanGate 15nm Open Cell Library ($V_{DD} = 0.8\text{ V}, f_{clk} = 200\text{ MHz}$)  
> **Execution Status:** **SUCCESS** (Completed in 2.97s)

---

## 1. Hardware Performance Comparison

| Metric | Exact Baseline | AxSYS Approx | Improvement |
| :--- | :---: | :---: | :---: |
| **Silicon Area** | 167.95 $\mu m^2$ | 146.08 $\mu m^2$ | **-13.02%** |
| **Total Power** | 21.458 $\mu\text{W}$ | 19.458 $\mu\text{W}$ | **-9.32%** |
| **Static Leakage** | 7.750 $\mu\text{W}$ | 6.981 $\mu\text{W}$ | -9.93% |
| **Dynamic Power** | 13.708 $\mu\text{W}$ | 12.477 $\mu\text{W}$ | -8.98% |
| **Standard Cells** | 530 cells | 476 cells | **7 gates pruned** |

---

## 2. Verification & Error Fidelity Metrics

- **Control Path Integrity:** **PASSED** (0 errors detected)
- **Mean Error Distance (MED):** **7.4840** (Target Bound $\le 8.0$)
- **Worst-Case Error (WCE):** **9.00**
- **Error Rate (ER):** **97.00%**
- **Mean Squared Error (MSED):** **63.0080**
- **Mean Relative Error (MRED):** **0.033548**
- **Signal Fidelity (SQNR):** **-17.99 dB**

---

## 3. Generated Files

- Input RTL: [`sobel.v`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/sobel/sobel.v)
- Approximated Netlist: [`final_approx_top.v`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/sobel/axsys_run/final_approx_top.v)
- Relaxed Timing Constraints: [`final_approx_top.sdc`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/sobel/axsys_run/final_approx_top.sdc)
- Machine Summary: [`summary.json`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/sobel/summary.json)
