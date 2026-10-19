# AxBench Benchmark Report: Inverse Kinematics (2-Joint) (`inversek2j`)

> **Application Domain:** Robotics & Motion Control  
> **Target Error Bound:** MED $\le 16.0$ (LSB Width = 4)  
> **Technology:** NanGate 15nm Open Cell Library ($V_{DD} = 0.8\text{ V}, f_{clk} = 200\text{ MHz}$)  
> **Execution Status:** **SUCCESS** (Completed in 5.40s)

---

## 1. Hardware Performance Comparison

| Metric | Exact Baseline | AxSYS Approx | Improvement |
| :--- | :---: | :---: | :---: |
| **Silicon Area** | 279.97 $\mu m^2$ | 249.54 $\mu m^2$ | **-10.87%** |
| **Total Power** | 35.909 $\mu\text{W}$ | 33.387 $\mu\text{W}$ | **-7.02%** |
| **Static Leakage** | 12.940 $\mu\text{W}$ | 11.833 $\mu\text{W}$ | -8.55% |
| **Dynamic Power** | 22.969 $\mu\text{W}$ | 21.554 $\mu\text{W}$ | -6.16% |
| **Standard Cells** | 873 cells | 826 cells | **13 gates pruned** |

---

## 2. Verification & Error Fidelity Metrics

- **Control Path Integrity:** **PASSED** (0 errors detected)
- **Mean Error Distance (MED):** **7.7040** (Target Bound $\le 16.0$)
- **Worst-Case Error (WCE):** **13.00**
- **Error Rate (ER):** **96.00%**
- **Mean Squared Error (MSED):** **78.2920**
- **Mean Relative Error (MRED):** **0.001119**
- **Signal Fidelity (SQNR):** **-18.94 dB**

---

## 3. Generated Files

- Input RTL: [`inversek2j.v`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/inversek2j/inversek2j.v)
- Approximated Netlist: [`final_approx_top.v`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/inversek2j/axsys_run/final_approx_top.v)
- Relaxed Timing Constraints: [`final_approx_top.sdc`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/inversek2j/axsys_run/final_approx_top.sdc)
- Machine Summary: [`summary.json`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/inversek2j/summary.json)
