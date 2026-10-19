# AxBench Benchmark Report: Feed-Forward Neural Network (`ffnn`)

> **Application Domain:** Machine Learning / Edge AI  
> **Target Error Bound:** MED $\le 8.0$ (LSB Width = 4)  
> **Technology:** NanGate 15nm Open Cell Library ($V_{DD} = 0.8\text{ V}, f_{clk} = 200\text{ MHz}$)  
> **Execution Status:** **SUCCESS** (Completed in 4.81s)

---

## 1. Hardware Performance Comparison

| Metric | Exact Baseline | AxSYS Approx | Improvement |
| :--- | :---: | :---: | :---: |
| **Silicon Area** | 195.67 $\mu m^2$ | 166.38 $\mu m^2$ | **-14.97%** |
| **Total Power** | 24.379 $\mu\text{W}$ | 22.223 $\mu\text{W}$ | **-8.84%** |
| **Static Leakage** | 8.952 $\mu\text{W}$ | 7.940 $\mu\text{W}$ | -11.30% |
| **Dynamic Power** | 15.426 $\mu\text{W}$ | 14.283 $\mu\text{W}$ | -7.41% |
| **Standard Cells** | 586 cells | 546 cells | **16 gates pruned** |

---

## 2. Verification & Error Fidelity Metrics

- **Control Path Integrity:** **PASSED** (0 errors detected)
- **Mean Error Distance (MED):** **3.9620** (Target Bound $\le 8.0$)
- **Worst-Case Error (WCE):** **15.00**
- **Error Rate (ER):** **51.20%**
- **Mean Squared Error (MSED):** **40.3660**
- **Mean Relative Error (MRED):** **0.005136**
- **Signal Fidelity (SQNR):** **-16.06 dB**

---

## 3. Generated Files

- Input RTL: [`ffnn.v`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/ffnn/ffnn.v)
- Approximated Netlist: [`final_approx_top.v`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/ffnn/axsys_run/final_approx_top.v)
- Relaxed Timing Constraints: [`final_approx_top.sdc`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/ffnn/axsys_run/final_approx_top.sdc)
- Machine Summary: [`summary.json`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/ffnn/summary.json)
