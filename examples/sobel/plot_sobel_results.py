"""Generate visualization plots for Sobel multi-cone approximation sweep."""

import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

def generate_plots() -> Path:
    summary_path = Path("build/sobel_sweep/sweep_summary.json")
    with open(summary_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    configs = [d["config"] for d in data]
    area_savings = [d["area_savings_percent"] for d in data]
    pruned_nodes = [d["pruned_nodes"] for d in data]
    statuses = [d["flow_status"] for d in data]

    sobel_out_med = []
    sobel_out_bound = []
    gy_med = []
    gy_bound = []
    gx_med = []
    gx_bound = []

    for d in data:
        metrics = {m["wire"]: m for m in d["metric_evaluations"]}
        sobel_out_med.append(metrics["sobel_out"]["measured"])
        sobel_out_bound.append(metrics["sobel_out"]["bound"])
        gy_med.append(metrics["gy_abs"]["measured"])
        gy_bound.append(metrics["gy_abs"]["bound"])
        gx_med.append(metrics["gx_abs"]["measured"])
        gx_bound.append(metrics["gx_abs"]["bound"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), dpi=150)

    # 1. Area Savings & Pruned Nodes
    x = np.arange(len(configs))
    bar_colors = ["#10b981" if s == "SUCCESS" else "#ef4444" for s in statuses]
    bars = ax1.bar(x, area_savings, color=bar_colors, width=0.55, edgecolor="#1f2937", linewidth=1.2)

    for idx, (bar, nodes, status) in enumerate(zip(bars, pruned_nodes, statuses)):
        h = bar.get_height()
        status_lbl = "PASS" if status == "SUCCESS" else "FAIL (bound)"
        ax1.text(bar.get_x() + bar.get_width() / 2, h + 0.3,
                 f"{h:.1f}%\n({nodes} gates)\n[{status_lbl}]",
                 ha="center", va="bottom", fontsize=8.5, fontweight="bold",
                 color="#065f46" if status == "SUCCESS" else "#991b1b")

    ax1.set_xticks(x)
    ax1.set_xticklabels(configs, rotation=15, fontsize=10)
    ax1.set_ylabel("Standard-Cell Area Savings (%)", fontsize=11, fontweight="bold")
    ax1.set_title("Sobel Operator: Gate Area Savings & Pruning Yield", fontsize=12, fontweight="bold")
    ax1.set_ylim(0, max(area_savings) + 3.5)
    ax1.grid(axis="y", linestyle="--", alpha=0.5)

    # 2. Multi-Cone Measured Errors
    w = 0.25
    x2 = np.arange(len(configs))
    ax2.plot(x2, sobel_out_med, marker="o", linewidth=2, color="#6366f1", label="sobel_out (Magnitude MED)")
    ax2.plot(x2, gy_med, marker="s", linewidth=2, color="#0ea5e9", label="gy_abs (Vertical MED)")
    ax2.plot(x2, gx_med, marker="^", linewidth=2, color="#f59e0b", label="gx_abs (Horizontal MED)")

    # Plot bounds as dashed reference lines
    ax2.plot(x2, sobel_out_bound, linestyle=":", color="#6366f1", alpha=0.7, label="sobel_out bound")
    ax2.plot(x2, gy_bound, linestyle=":", color="#0ea5e9", alpha=0.7, label="gy_abs bound")

    ax2.set_xticks(x2)
    ax2.set_xticklabels(configs, rotation=15, fontsize=10)
    ax2.set_ylabel("Measured Mean Error Distance (MED)", fontsize=11, fontweight="bold")
    ax2.set_title("Multi-Cone Error Trajectory (Measured vs Bound)", fontsize=12, fontweight="bold")
    ax2.legend(loc="upper left", fontsize=8.5)
    ax2.grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()
    out_png = Path("build/sobel_sweep/sobel_tradeoff.png").resolve()
    plt.savefig(out_png)
    plt.close()
    print(f"Plot saved to {out_png}")
    return out_png

if __name__ == "__main__":
    generate_plots()
