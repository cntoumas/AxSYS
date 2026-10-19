"""Generate High-Resolution, Clean EDA Power and Area Dashboard Visualizations.

Produces publication-grade dashboard figures with zero visual overlaps, ample spacing,
and clear typography for both the INT8 Systolic PE and 4-Lane Vector Dot Product.
"""

import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

# Set clean styling
plt.rcParams['font.sans-serif'] = 'DejaVu Sans'
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.edgecolor'] = '#333333'
plt.rcParams['axes.linewidth'] = 0.8


def plot_systolic_pe_dashboard(sweep_json: Path, output_png: Path):
    with open(sweep_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    cfg_labels = ["Light\n(B=8.0, LSB=2)", "Conservative\n(B=16.0, LSB=4)", 
                  "Moderate\n(B=32.0, LSB=6)", "Aggressive\n(B=64.0, LSB=8)", 
                  "Over-Pushed\n(B=4.0, LSB=8)"]
    area_savings = [d.get("area_savings_percent", 0.0) for d in data]
    pwr_savings = [d.get("power_savings_percent", 0.0) for d in data]
    total_pwrs = [d.get("total_power_uw", 0.0) for d in data]
    leak_pwrs = [d.get("leakage_power_uw", 0.0) for d in data]
    dyn_pwrs = [d.get("dynamic_power_uw", 0.0) for d in data]
    meds = [d.get("measured_med", 0.0) for d in data]
    bounds = [d.get("bound", 0.0) for d in data]
    pruned = [d.get("pruned_nodes_count", 0) for d in data]
    verif = [d.get("verification_status", "UNKNOWN") for d in data]

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(20, 6.2))
    x = np.arange(len(cfg_labels))
    width = 0.45

    # --- PANEL 1: AREA REDUCTION ---
    colors_area = ["#2b8a3e" if v == "PASSED" else "#c92a2a" for v in verif]
    bars1 = ax1.bar(x, area_savings, width, color=colors_area, alpha=0.88, edgecolor="#212529", linewidth=1.2)
    ax1.set_ylabel("Cell Area Savings (%)", fontsize=12, fontweight="bold", labelpad=10)
    ax1.set_title("(a) Standard-Cell Area Reduction\n(NanGate 15nm)", fontsize=13, fontweight="bold", pad=12)
    ax1.set_xticks(x)
    ax1.set_xticklabels(cfg_labels, fontsize=10)
    ax1.set_ylim(0, max(area_savings) * 1.45)
    ax1.grid(axis="y", linestyle=":", alpha=0.6)

    for bar, s, p in zip(bars1, area_savings, pruned):
        h = bar.get_height()
        ax1.annotate(f"{s:.2f}%\n({p} gates)", xy=(bar.get_x() + bar.get_width() / 2, h),
                     xytext=(0, 6), textcoords="offset points", ha="center", va="bottom",
                     fontsize=9.5, fontweight="bold", color="#212529")

    # --- PANEL 2: POWER DISSIPATION & BREAKDOWN ---
    bars_leak = ax2.bar(x, leak_pwrs, width, label="Static Leakage Power", color="#1c7ed6", alpha=0.9, edgecolor="#212529", linewidth=1.0)
    bars_dyn = ax2.bar(x, dyn_pwrs, width, bottom=leak_pwrs, label="Dynamic Switching Power", color="#f76707", alpha=0.9, edgecolor="#212529", linewidth=1.0)
    ax2.axhline(20.386, color="#495057", linestyle="--", linewidth=1.5, label="Exact Baseline (20.39 uW)")
    ax2.set_ylabel("Power Dissipation (uW @ 100 MHz)", fontsize=12, fontweight="bold", labelpad=10)
    ax2.set_title("(b) Power Dissipation Breakdown\n(Static Leakage vs Dynamic)", fontsize=13, fontweight="bold", pad=12)
    ax2.set_xticks(x)
    ax2.set_xticklabels(cfg_labels, fontsize=10)
    ax2.set_ylim(0, 26.0)
    ax2.legend(loc="upper right", fontsize=9.5, framealpha=0.95)
    ax2.grid(axis="y", linestyle=":", alpha=0.6)

    for i, (tot, p_sav) in enumerate(zip(total_pwrs, pwr_savings)):
        ax2.annotate(f"{tot:.2f} uW\n(-{p_sav:.1f}%)", xy=(i, tot), xytext=(0, 5), textcoords="offset points",
                     ha="center", va="bottom", fontsize=9.5, fontweight="bold", color="#1864ab")

    # --- PANEL 3: VERIFICATION & ERROR DISTANCE ---
    ax3.plot(x, bounds, label="Annotated Bound (axc_bound)", marker="s", markersize=7, linestyle="--", color="#1c7ed6", linewidth=2.0)
    ax3.plot(x, meds, label="Measured Miter Error (MED)", marker="o", markersize=8, linestyle="-", color="#e03131", linewidth=2.2)
    ax3.set_ylabel("Mean Error Distance (MED)", fontsize=12, fontweight="bold", labelpad=10)
    ax3.set_title("(c) Cycle-Accurate Miter Verification\n(Zero Control Corruption Guaranteed)", fontsize=13, fontweight="bold", pad=12)
    ax3.set_xticks(x)
    ax3.set_xticklabels(cfg_labels, fontsize=10)
    ax3.set_ylim(-2, max(meds) * 1.35)
    ax3.legend(loc="upper left", fontsize=10, framealpha=0.95)
    ax3.grid(True, linestyle=":", alpha=0.6)

    for i, (m, b, v) in enumerate(zip(meds, bounds, verif)):
        status_txt = "PASSED" if v == "PASSED" else "VIOLATION"
        color_txt = "#2b8a3e" if v == "PASSED" else "#c92a2a"
        ax3.annotate(f"MED={m:.1f}\n[{status_txt}]", xy=(i, m), xytext=(0, 10), textcoords="offset points",
                     ha="center", va="bottom", fontsize=9, fontweight="bold", color=color_txt)

    plt.suptitle("AxSYS Approximate EDA Flow: INT8 Systolic Processing Element (pe.sv)\nStandard-Cell Area & Power Optimization Dashboard", fontsize=15, fontweight="bold", y=1.03)
    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=300, bbox_inches="tight")
    print(f"Systolic PE Dashboard saved: {output_png}")


def plot_dot_product_dashboard(output_png: Path):
    labels = ["Exact Baseline\n(Full 8-bit)", "1-LSB Approx\n(Upper 7-bit)", "2-LSB Approx\n(Upper 6-bit)", "3-LSB Approx\n(Upper 5-bit)"]
    cells = [1559, 1135, 815, 554]
    areas = [487.19, 357.29, 255.25, 172.77]
    area_savings = [0.0, 26.66, 47.61, 64.54]

    leak_pwrs = [21.057, 15.062, 10.731, 7.387]
    dyn_pwrs = [21.233, 15.645, 11.186, 7.559]
    total_pwrs = [42.290, 30.708, 21.917, 14.946]
    pwr_savings = [0.0, 27.39, 48.17, 64.66]

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(20, 6.2))
    x = np.arange(len(labels))
    width = 0.45

    # --- PANEL 1: AREA & GATE COUNT ---
    bars1 = ax1.bar(x, areas, width, color="#2b8a3e", alpha=0.88, edgecolor="#212529", linewidth=1.2)
    ax1.set_ylabel("Standard Cell Area (um^2)", fontsize=12, fontweight="bold", labelpad=10)
    ax1.set_title("(a) Gate Area & Cell Count Reduction\n(4 Parallel 8x8 Multipliers + Adder Tree)", fontsize=13, fontweight="bold", pad=12)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=10)
    ax1.set_ylim(0, max(areas) * 1.35)
    ax1.grid(axis="y", linestyle=":", alpha=0.6)

    for bar, a, c, s in zip(bars1, areas, cells, area_savings):
        sav_str = f"-{s:.1f}% Area" if s > 0 else "Baseline"
        ax1.annotate(f"{a:.1f} um^2\n({c} cells)\n[{sav_str}]", xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                     xytext=(0, 5), textcoords="offset points", ha="center", va="bottom",
                     fontsize=9, fontweight="bold", color="#212529")

    # --- PANEL 2: POWER DISSIPATION ---
    bars_leak = ax2.bar(x, leak_pwrs, width, label="Static Leakage Power", color="#1c7ed6", alpha=0.9, edgecolor="#212529", linewidth=1.0)
    bars_dyn = ax2.bar(x, dyn_pwrs, width, bottom=leak_pwrs, label="Dynamic Switching Power", color="#f76707", alpha=0.9, edgecolor="#212529", linewidth=1.0)
    ax2.set_ylabel("Power Dissipation (uW @ 100 MHz)", fontsize=12, fontweight="bold", labelpad=10)
    ax2.set_title("(b) Static & Dynamic Power Dissipation\n(NanGate 15nm, Vdd = 0.8V)", fontsize=13, fontweight="bold", pad=12)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=10)
    ax2.set_ylim(0, max(total_pwrs) * 1.35)
    ax2.legend(loc="upper right", fontsize=10, framealpha=0.95)
    ax2.grid(axis="y", linestyle=":", alpha=0.6)

    for i, (tot, p_sav) in enumerate(zip(total_pwrs, pwr_savings)):
        sav_str = f"-{p_sav:.1f}%" if p_sav > 0 else "Baseline"
        ax2.annotate(f"{tot:.2f} uW\n({sav_str})", xy=(i, tot), xytext=(0, 5), textcoords="offset points",
                     ha="center", va="bottom", fontsize=9.5, fontweight="bold", color="#1864ab")

    # --- PANEL 3: SCALING PARETO CURVE ---
    ax3.plot(area_savings, pwr_savings, marker="o", markersize=9, linewidth=2.5, color="#7048e8", label="Power vs Area Pareto")
    for a, p, lab in zip(area_savings, pwr_savings, ["Baseline", "1-LSB", "2-LSB", "3-LSB"]):
        ax3.annotate(f"{lab}\n({a:.1f}% Area, {p:.1f}% Power)", xy=(a, p), xytext=(10, -15 if p > 50 else 10),
                     textcoords="offset points", fontsize=9.5, fontweight="bold", color="#5f3dc4",
                     arrowprops=dict(arrowstyle="->", color="#7048e8", lw=1.2))

    ax3.set_xlabel("Area Savings (%)", fontsize=12, fontweight="bold", labelpad=10)
    ax3.set_ylabel("Power Savings (%)", fontsize=12, fontweight="bold", labelpad=10)
    ax3.set_title("(c) Joint Power-Area Efficiency Scaling\n(Proportional 1:1 Co-Optimization)", fontsize=13, fontweight="bold", pad=12)
    ax3.set_xlim(-5, 75)
    ax3.set_ylim(-5, 75)
    ax3.grid(True, linestyle=":", alpha=0.6)
    ax3.legend(loc="lower right", fontsize=10)

    plt.suptitle("AxSYS Multi-Lane Datapath: 4-Lane Vector Dot Product (vector_dot_product.sv)\nParallel Multiplier Array Power & Area Scaling Dashboard", fontsize=15, fontweight="bold", y=1.03)
    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=300, bbox_inches="tight")
    print(f"Dot Product Dashboard saved: {output_png}")


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent
    sweep_json = repo_root / "build" / "systolic_pe_sweep" / "pe_sweep_results.json"
    out_pe = repo_root / "build" / "systolic_pe_sweep" / "dashboard_systolic_pe.png"
    out_vdp = repo_root / "build" / "systolic_pe_sweep" / "dashboard_dot_product.png"

    if sweep_json.exists():
        plot_systolic_pe_dashboard(sweep_json, out_pe)
    plot_dot_product_dashboard(out_vdp)
