# AxBench Benchmark Report: FIR Filter (`fir`)

> **Application Domain:** Digital Signal Processing  
> **Target Error Bound:** MED $\le 16.0$ (LSB Width = 5)  
> **Technology:** NanGate 15nm Open Cell Library ($V_{DD} = 0.8\text{ V}, f_{clk} = 200\text{ MHz}$)  
> **Execution Status:** **SUCCESS** (Completed in 3.62s)

---

## 1. Hardware Performance Comparison

| Metric | Exact Baseline | AxSYS Approx | Improvement |
| :--- | :---: | :---: | :---: |
| **Silicon Area** | 230.87 $\mu m^2$ | 140.97 $\mu m^2$ | **-38.94%** |
| **Total Power** | 25.755 $\mu\text{W}$ | 18.867 $\mu\text{W}$ | **-26.74%** |
| **Static Leakage** | 10.038 $\mu\text{W}$ | 6.662 $\mu\text{W}$ | -33.64% |
| **Dynamic Power** | 15.717 $\mu\text{W}$ | 12.206 $\mu\text{W}$ | -22.34% |
| **Standard Cells** | 587 cells | 464 cells | **17 gates pruned** |

---

## 2. Verification & Error Fidelity Metrics

- **Control Path Integrity:** **PASSED** (0 errors detected)
- **Mean Error Distance (MED):** **14.0840** (Target Bound $\le 16.0$)
- **Worst-Case Error (WCE):** **30.00**
- **Error Rate (ER):** **93.60%**
- **Mean Squared Error (MSED):** **279.6400**
- **Mean Relative Error (MRED):** **0.026031**
- **Signal Fidelity (SQNR):** **-24.47 dB**

---

## 3. Generated Files

- Input RTL: [`fir.v`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/fir/fir.v)
- Approximated Netlist: [`final_approx_top.v`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/fir/axsys_run/final_approx_top.v)
- Relaxed Timing Constraints: [`final_approx_top.sdc`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/fir/axsys_run/final_approx_top.sdc)
- Machine Summary: [`summary.json`](file:///home/christos-ntoumas/AxSYS/axbench_benchmarking/fir/summary.json)
