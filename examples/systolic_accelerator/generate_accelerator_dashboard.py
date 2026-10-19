"""Generate Publication-Quality Visual Dashboard for the Complete Systolic Accelerator.

Creates high-resolution, non-overlapping visual plots displaying:
1. Silicon Area and Cell Count Reduction across approximation levels (4x4 Tensor Core)
2. Static Leakage vs Dynamic Power Dissipation Breakdown (4x4 Tensor Core)
3. Multi-PE Array Scaling: Compounding savings from 1 PE -> 16 PEs (4x4) -> 64 PEs (8x8)
4. Frobenius Norm Accuracy vs Power-Area Pareto Efficiency Frontier
"""

import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RESULTS_FILE = Path("/home/christos-ntoumas/AxSYS/build/accelerator_sweep/accelerator_sweep_results.json")
ARTIFACT_DIR = Path("/home/christos-ntoumas/.gemini/antigravity-cli/brain/e307950d-ab38-4a9a-a41a-8a0aa8fe367e")
OUTPUT_PNG = ARTIFACT_DIR / "dashboard_accelerator.png"

with open(RESULTS_FILE, "r") as f:
    data = json.load(f)

# Filter 4x4 configs
cfgs_4x4 = [d for d in data if d["scale"] == "4x4"]
labels_4x4 = ["Exact", "Light\n(LSB=2)", "Conserv.\n(LSB=4)", "Moderate\n(LSB=6)", "Aggress.\n(LSB=8)"]
area_4x4 = [d["area_um2"] for d in cfgs_4x4]
cell_4x4 = [d["cell_count"] for d in cfgs_4x4]
leak_4x4 = [d["leakage_power_uw"] for d in cfgs_4x4]
dyn_4x4 = [d["dynamic_power_uw"] for d in cfgs_4x4]
tot_pwr_4x4 = [d["total_power_uw"] for d in cfgs_4x4]
pwr_red_4x4 = [d["power_reduction_pct"] for d in cfgs_4x4]
area_red_4x4 = [d["area_reduction_pct"] for d in cfgs_4x4]
frob_err_4x4 = [d["sim_metrics"]["frobenius_err_pct"] for d in cfgs_4x4]

# Scaling configs (at LSB=4)
# 1 PE data from previous run: area saved = 22.71 um2, power saved = 1.63 uW
# 4x4 (16 PEs): area saved = 459.08 um2, power saved = 32.11 uW
# 8x8 (64 PEs): area saved = 1938.84 um2, power saved = 136.18 uW
scale_labels = ["Single PE\n(1 PE)", "4x4 Tensor Core\n(16 PEs)", "8x8 Tensor Core\n(64 PEs)"]
scale_area_saved = [22.71, 6443.98 - 5984.90, 25727.97 - 23789.13]
scale_power_saved = [1.63, 464.98 - 432.87, 1860.34 - 1724.16]

# Create Figure
fig, axes = plt.subplots(2, 2, figsize=(16, 12), dpi=300)
plt.subplots_adjust(hspace=0.35, wspace=0.28)

colors = {
    "primary": "#1f77b4",
    "secondary": "#ff7f0e",
    "leakage": "#d62728",
    "dynamic": "#2ca02c",
    "accent": "#9467bd",
    "sweet_spot": "#2ca02c"
}

# -------------------------------------------------------------
# Panel 1: Accelerator Area & Cell Count Reduction (4x4)
# -------------------------------------------------------------
ax1 = axes[0, 0]
x = np.arange(len(labels_4x4))
width = 0.38

bars_area = ax1.bar(x - width/2, area_4x4, width, label="Silicon Area (um²)", color="#1f77b4", alpha=0.88, edgecolor="black", linewidth=0.8)
ax1.set_ylabel("Silicon Area (um²)", color="#1f77b4", fontsize=11, fontweight="bold")
ax1.tick_params(axis="y", labelcolor="#1f77b4")
ax1.set_ylim(0, 7500)

ax1_twin = ax1.twinx()
bars_cells = ax1_twin.bar(x + width/2, cell_4x4, width, label="Cell Count", color="#17becf", alpha=0.88, edgecolor="black", linewidth=0.8)
ax1_twin.set_ylabel("Standard Cell Count", color="#0e808e", fontsize=11, fontweight="bold")
ax1_twin.tick_params(axis="y", labelcolor="#0e808e")
ax1_twin.set_ylim(0, 20000)

ax1.set_xticks(x)
ax1.set_xticklabels(labels_4x4, fontsize=9.5, fontweight="medium")
ax1.set_title("A: 4x4 Accelerator Silicon Area & Gate Count Scaling", fontsize=12, fontweight="bold", pad=12)
ax1.grid(axis="y", linestyle="--", alpha=0.4)

# Value labels on area bars
for b, red in zip(bars_area, area_red_4x4):
    h = b.get_height()
    txt = f"{h:.0f}\n(-{red:.1f}%)" if red > 0 else f"{h:.0f}"
    ax1.annotate(txt, (b.get_x() + b.get_width() / 2, h + 150),
                 ha="center", va="bottom", fontsize=8, fontweight="bold", color="#1f77b4")

# Value labels on cell bars
for b in bars_cells:
    h = b.get_height()
    ax1_twin.annotate(f"{h:,}", (b.get_x() + b.get_width() / 2, h + 300),
                     ha="center", va="bottom", fontsize=8, color="#0e808e")

# Combined legend
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax1_twin.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", framealpha=0.9, fontsize=9)

# -------------------------------------------------------------
# Panel 2: Power Dissipation Breakdown (Static vs Dynamic)
# -------------------------------------------------------------
ax2 = axes[0, 1]
bars_dyn = ax2.bar(x, dyn_4x4, width=0.5, label="Dynamic Switching Power (uW)", color="#2ca02c", alpha=0.88, edgecolor="black", linewidth=0.8)
bars_leak = ax2.bar(x, leak_4x4, width=0.5, bottom=dyn_4x4, label="Static Leakage Power (uW)", color="#d62728", alpha=0.88, edgecolor="black", linewidth=0.8)

ax2.set_ylabel("Power Dissipation @ 100MHz (uW)", fontsize=11, fontweight="bold")
ax2.set_xticks(x)
ax2.set_xticklabels(labels_4x4, fontsize=9.5, fontweight="medium")
ax2.set_ylim(0, 560)
ax2.set_title("B: 4x4 Accelerator Power Dissipation Breakdown (NanGate 15nm)", fontsize=12, fontweight="bold", pad=12)
ax2.grid(axis="y", linestyle="--", alpha=0.4)

# Percentage power reduction secondary axis
ax2_twin = ax2.twinx()
ax2_twin.plot(x, pwr_red_4x4, color="#9467bd", marker="s", markersize=7, linewidth=2.2, label="Total Power Cut (%)")
ax2_twin.set_ylabel("Total Power Reduction (%)", color="#9467bd", fontsize=11, fontweight="bold")
ax2_twin.tick_params(axis="y", labelcolor="#9467bd")
ax2_twin.set_ylim(-2, 22)

for i, p_val in enumerate(tot_pwr_4x4):
    red = pwr_red_4x4[i]
    lbl = f"{p_val:.1f} uW" + (f"\n(-{red:.1f}%)" if red > 0 else "")
    ax2.annotate(lbl, (x[i], p_val + 10), ha="center", va="bottom", fontsize=8, fontweight="bold")

lines_p1, labs_p1 = ax2.get_legend_handles_labels()
lines_p2, labs_p2 = ax2_twin.get_legend_handles_labels()
ax2.legend(lines_p1 + lines_p2, labs_p1 + labs_p2, loc="upper right", framealpha=0.9, fontsize=9)

# -------------------------------------------------------------
# Panel 3: Multi-PE Array Scaling Compounding (1 PE -> 16 -> 64)
# -------------------------------------------------------------
ax3 = axes[1, 0]
x_scale = np.arange(len(scale_labels))
width_s = 0.35

bars_s_area = ax3.bar(x_scale - width_s/2, scale_area_saved, width_s, label="Silicon Area Saved (um²)", color="#ff7f0e", alpha=0.9, edgecolor="black", linewidth=0.8)
ax3.set_ylabel("Silicon Area Eliminated (um²)", color="#d95f02", fontsize=11, fontweight="bold")
ax3.tick_params(axis="y", labelcolor="#d95f02")
ax3.set_ylim(0, 2400)

ax3_twin = ax3.twinx()
bars_s_pwr = ax3_twin.bar(x_scale + width_s/2, scale_power_saved, width_s, label="Total Power Saved (uW)", color="#2ca02c", alpha=0.85, edgecolor="black", linewidth=0.8)
ax3_twin.set_ylabel("Power Dissipation Saved (uW)", color="#1b7837", fontsize=11, fontweight="bold")
ax3_twin.tick_params(axis="y", labelcolor="#1b7837")
ax3_twin.set_ylim(0, 170)

ax3.set_xticks(x_scale)
ax3.set_xticklabels(scale_labels, fontsize=10, fontweight="bold")
ax3.set_title("C: Multi-PE Array Scaling: Compounding Global Savings (at LSB=4)", fontsize=12, fontweight="bold", pad=12)
ax3.grid(axis="y", linestyle="--", alpha=0.4)

for b in bars_s_area:
    h = b.get_height()
    ax3.annotate(f"{h:.1f} um²", (b.get_x() + b.get_width()/2, h + 45),
                 ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#d95f02")

for b in bars_s_pwr:
    h = b.get_height()
    ax3_twin.annotate(f"{h:.1f} uW", (b.get_x() + b.get_width()/2, h + 3.5),
                      ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#1b7837")

lines_s1, labs_s1 = ax3.get_legend_handles_labels()
lines_s2, labs_s2 = ax3_twin.get_legend_handles_labels()
ax3.legend(lines_s1 + lines_s2, labs_s1 + labs_s2, loc="upper left", framealpha=0.9, fontsize=9)

# -------------------------------------------------------------
# Panel 4: Accuracy vs Power-Area Pareto Frontier (4x4 Tensor Core)
# -------------------------------------------------------------
ax4 = axes[1, 1]

# Plot Pareto points
scatter = ax4.scatter(frob_err_4x4[1:], pwr_red_4x4[1:], c=area_red_4x4[1:], cmap="viridis", s=140, edgecolors="black", linewidth=1.2, zorder=5)
cbar = plt.colorbar(scatter, ax=ax4)
cbar.set_label("Silicon Area Reduction (%)", fontsize=10, fontweight="bold")

# Plot line
ax4.plot(frob_err_4x4, pwr_red_4x4, linestyle="--", color="#333333", alpha=0.7, zorder=3)

# Highlight sweet spot
ax4.axvspan(-0.1, 1.2, color="#2ca02c", alpha=0.12, label="Sweet Spot (< 1.2% Frobenius Err)")
ax4.axvline(1.2, color="#2ca02c", linestyle=":", linewidth=1.5)

cfg_tags = ["Light (LSB=2)", "Conserv. (LSB=4)", "Moderate (LSB=6)", "Aggress. (LSB=8)"]
offsets = [(0.15, 0.4), (0.2, -0.6), (0.2, 0.5), (-1.2, 0.6)]
for i, tag in enumerate(cfg_tags):
    fx = frob_err_4x4[i+1]
    fy = pwr_red_4x4[i+1]
    ox, oy = offsets[i]
    ax4.annotate(
        f"{tag}\nErr: {fx:.2f}% | Pwr: -{fy:.1f}%",
        xy=(fx, fy),
        xytext=(fx + ox, fy + oy),
        arrowprops=dict(arrowstyle="->", color="black", lw=1.0),
        fontsize=8.5,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#cccccc", alpha=0.9)
    )

ax4.set_xlabel("Frobenius Norm Relative Error on Matrix Product (%)", fontsize=11, fontweight="bold")
ax4.set_ylabel("Accelerator Power Reduction (%)", fontsize=11, fontweight="bold")
ax4.set_title("D: Tensor Core Matrix Accuracy vs Power Reduction Pareto Frontier", fontsize=12, fontweight="bold", pad=12)
ax4.grid(True, linestyle="--", alpha=0.4)
ax4.set_xlim(-0.2, 5.5)
ax4.set_ylim(-1, 18)
ax4.legend(loc="lower right", framealpha=0.9, fontsize=9)

plt.suptitle(
    "AxSYS Attribute-Driven Approximate Logic Synthesis: Complete Hardware Accelerator Evaluation\n"
    "Multi-PE 2D Systolic Tensor Cores (NanGate 15nm Standard Cell Library @ 100 MHz, VDD=0.8V)",
    fontsize=14,
    fontweight="bold",
    y=0.99
)

plt.tight_layout(rect=[0, 0.02, 1, 0.96])
plt.savefig(OUTPUT_PNG, dpi=300)
plt.close()
print(f"Publication-grade accelerator dashboard saved to: {OUTPUT_PNG}")
