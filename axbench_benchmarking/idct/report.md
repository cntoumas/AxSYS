# AxBench Benchmark Report: Inverse Discrete Cosine Transform (`idct`)

> **Application Domain:** Multimedia / Video Processing  
> **Target Error Bound:** MED $\le 16.0$ (LSB Width = 4)  
> **Technology:** NanGate 15nm Open Cell Library ($V_{DD} = 0.8\text{ V}, f_{clk} = 200\text{ MHz}$)  
> **Execution Status:** **SUCCESS** (Completed in 2.81s)

---

## 1. Hardware Performance Comparison

| Metric | Exact Baseline | AxSYS Approx | Improvement |
| :--- | :---: | :---: | :---: |
| **Silicon Area** | 135.46 $\mu m^2$ | 109.90 $\mu m^2$ | **-18.87%** |
| **Total Power** | 16.355 $\mu\text{W}$ | 14.575 $\mu\text{W}$ | **-10.88%** |
| **Static Leakage** | 6.093 $\mu\text{W}$ | 5.098 $\mu\text{W}$ | -16.34% |
| **Dynamic Power** | 10.261 $\mu\text{W}$ | 9.477 $\mu\text{W}$ | -7.64% |
| **Standard Cells** | 382 cells | 348 cells | **13 gates pruned** |

---

## 2. Verification & Error Fidelity Metrics

- **Control Path Integrity:** **PASSED** (0 errors detected)
- **Mean Error Distance (MED):** **7.6780** (Target Bound $\le 16.0$)
- **Worst-Case Error (WCE):** **15.00**
- **Error Rate (ER):** **94.40%**
- **Mean Squared Error (MSED):** **78.8460**
- **Mean Relative Error (MRED):** **0.014601**
- **Signal Fidelity (SQNR):** **-18.97 dB**

---

## 3. Generated Files

- Input RTL: [`idct.v`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/idct/idct.v)
- Approximated Netlist: [`final_approx_top.v`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/idct/axsys_run/final_approx_top.v)
- Relaxed Timing Constraints: [`final_approx_top.sdc`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/idct/axsys_run/final_approx_top.sdc)
- Machine Summary: [`summary.json`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/idct/summary.json)
