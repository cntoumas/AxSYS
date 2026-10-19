"""Plot Error-Area-Power Tradeoffs for Systolic PE.

Generates visual tradeoff plots for the parameter sweep on the INT8 systolic PE,
illustrating area reduction, power reduction (leakage & dynamic), MED error distance,
and zero-control-error verification.
"""

import json
from pathlib import Path
import matplotlib.pyplot as plt

def generate_plots(results_json: Path, output_png: Path):
    with open(results_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    cfgs = [d["config_id"] for d in data]
    savings = [d.get("area_savings_percent", 0.0) or 0.0 for d in data]
    pwr_savings = [d.get("power_savings_percent", 0.0) or 0.0 for d in data]
    total_pwrs = [d.get("total_power_uw", 0.0) or 0.0 for d in data]
    leak_pwrs = [d.get("leakage_power_uw", 0.0) or 0.0 for d in data]
    dyn_pwrs = [d.get("dynamic_power_uw", 0.0) or 0.0 for d in data]
    meds = [d.get("measured_med", 0.0) or 0.0 for d in data]
    bounds = [d.get("bound", 0.0) for d in data]
    pruned = [d.get("pruned_nodes_count", 0) for d in data]
    verif = [d.get("verification_status", "UNKNOWN") for d in data]

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 5.5))

    # Panel 1: Area Savings
    colors = ["#2ca02c" if v == "PASSED" else "#d62728" for v in verif]
    x_pos = range(len(cfgs))

    bars1 = ax1.bar(x_pos, savings, color=colors, alpha=0.85, edgecolor="black", width=0.55)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(cfgs, rotation=25, ha="right", fontsize=9)
    ax1.set_ylabel("Area Savings (%)", fontsize=11, fontweight="bold")
    ax1.set_title("Cell Area Savings (NanGate 15nm)", fontsize=12, fontweight="bold")
    ax1.grid(axis="y", linestyle="--", alpha=0.5)

    for bar, s, p in zip(bars1, savings, pruned):
        height = bar.get_height()
        ax1.annotate(f"{s:.1f}%\n({p} gates)",
                     xy=(bar.get_x() + bar.get_width() / 2, height),
                     xytext=(0, 3), textcoords="offset points",
                     ha="center", va="bottom", fontsize=8.5, fontweight="bold")

    # Panel 2: Power Dissipation & Savings
    bars_leak = ax2.bar(x_pos, leak_pwrs, label="Leakage Power (uW)", color="#1f77b4", alpha=0.85, edgecolor="black", width=0.55)
    bars_dyn = ax2.bar(x_pos, dyn_pwrs, bottom=leak_pwrs, label="Dynamic Power (uW)", color="#ff7f0e", alpha=0.85, edgecolor="black", width=0.55)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(cfgs, rotation=25, ha="right", fontsize=9)
    ax2.set_ylabel("Power Dissipation (uW)", fontsize=11, fontweight="bold")
    ax2.set_title("Static & Dynamic Power Dissipation (100 MHz)", fontsize=12, fontweight="bold")
    ax2.legend(loc="upper right", fontsize=9)
    ax2.grid(axis="y", linestyle="--", alpha=0.5)

    for i, (tot, p_sav) in enumerate(zip(total_pwrs, pwr_savings)):
        ax2.annotate(f"{tot:.2f} uW\n(-{p_sav:.1f}%)",
                     xy=(i, tot), xytext=(0, 3), textcoords="offset points",
                     ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#111111")

    # Panel 3: Measured MED vs Target Bound
    ax3.plot(x_pos, bounds, label="Target Bound (MED)", marker="s", linestyle="--", color="#1f77b4", linewidth=2)
    ax3.plot(x_pos, meds, label="Measured Miter MED", marker="o", linestyle="-", color="#d62728", linewidth=2.5)
    ax3.set_xticks(x_pos)
    ax3.set_xticklabels(cfgs, rotation=25, ha="right", fontsize=9)
    ax3.set_ylabel("Mean Error Distance (MED)", fontsize=11, fontweight="bold")
    ax3.set_title("Cycle-Accurate Miter Error vs Target Bound", fontsize=12, fontweight="bold")
    ax3.legend(loc="upper left", fontsize=9.5)
    ax3.grid(True, linestyle="--", alpha=0.5)

    for x, m, b, v in zip(x_pos, meds, bounds, verif):
        status_txt = "PASS" if v == "PASSED" else "FAIL"
        color_txt = "green" if v == "PASSED" else "red"
        ax3.annotate(f"{m:.1f} ({status_txt})",
                     xy=(x, m), xytext=(0, 8), textcoords="offset points",
                     ha="center", va="bottom", fontsize=8.5, fontweight="bold", color=color_txt)

    plt.suptitle("AxSYS: INT8 Systolic Processing Element (ratshgupta-guptar76)\nArea, Power & Error Verification Tradeoffs", fontsize=13, fontweight="bold")
    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=300)
    print(f"Plot saved to {output_png}")

if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent
    res_path = repo_root / "build" / "systolic_pe_sweep" / "pe_sweep_results.json"
    out_plot = repo_root / "build" / "systolic_pe_sweep" / "systolic_pe_tradeoff.png"
    if res_path.exists():
        generate_plots(res_path, out_plot)
    else:
        print(f"Results file not found: {res_path}")
