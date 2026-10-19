"""Generate High-Resolution Visual Dashboard for FPGA (Xilinx Artix-7) Synthesis.

Visualizes:
1. Look-Up Table (LUT) breakdown by primitive type (LUT2..LUT6) across approximation levels.
2. Flip-Flop (FDCE) and CARRY4 chain reduction.
3. Multi-PE Array Scaling on Artix-7 (4x4 vs 8x8 cores).
4. Artix-7 XC7A35T Device Utilization vs Frobenius Matrix Accuracy Pareto Frontier.
"""

import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RESULTS_FILE = Path("/home/christos-ntoumas/AxSYS/build/accelerator_sweep/fpga_artix7_sweep_results.json")
ARTIFACT_DIR = Path("/home/christos-ntoumas/.gemini/antigravity-cli/brain/e307950d-ab38-4a9a-a41a-8a0aa8fe367e")
OUTPUT_PNG = ARTIFACT_DIR / "dashboard_fpga_artix7.png"

with open(RESULTS_FILE, "r") as f:
    data = json.load(f)

cfgs_4x4 = [d for d in data if d["scale"] == "4x4"]
labels_4x4 = ["Exact", "Light\n(LSB=2)", "Conserv.\n(LSB=4)", "Moderate\n(LSB=6)", "Aggress.\n(LSB=8)"]

total_luts_4x4 = [d["total_luts"] for d in cfgs_4x4]
carry4_4x4 = [d["carry4"] for d in cfgs_4x4]
ffs_4x4 = [d["ffs"] for d in cfgs_4x4]
lut_red_4x4 = [d["lut_reduction_pct"] for d in cfgs_4x4]
ff_saved_4x4 = [cfgs_4x4[0]["ffs"] - d["ffs"] for d in cfgs_4x4]
carry_saved_4x4 = [cfgs_4x4[0]["carry4"] - d["carry4"] for d in cfgs_4x4]
frob_err_4x4 = [d["sim_metrics"]["frobenius_err_pct"] for d in cfgs_4x4]
artix_util_4x4 = [d["artix7_35t_lut_util_pct"] for d in cfgs_4x4]

# LUT types for stacked bar
lut_types = ["LUT2", "LUT3", "LUT4", "LUT5", "LUT6"]
lut_stack = {lt: [d["luts_by_type"].get(lt, 0) for d in cfgs_4x4] for lt in lut_types}

# 8x8 data
cfg_8x8_exact = next(d for d in data if d["config_id"] == "fpga_exact_8x8")
cfg_8x8_approx = next(d for d in data if d["config_id"] == "fpga_approx_8x8")

fig, axes = plt.subplots(2, 2, figsize=(16, 12), dpi=300)
plt.subplots_adjust(hspace=0.35, wspace=0.28)

colors = {
    "LUT2": "#aec7e8",
    "LUT3": "#7bccc4",
    "LUT4": "#43a2ca",
    "LUT5": "#0868ac",
    "LUT6": "#084081",
    "FF": "#2ca02c",
    "CARRY4": "#d95f02",
}

# -------------------------------------------------------------
# Panel A: Stacked LUT Breakdown (LUT2..LUT6)
# -------------------------------------------------------------
ax1 = axes[0, 0]
x = np.arange(len(labels_4x4))
width = 0.52

bottom = np.zeros(len(labels_4x4))
for lt in lut_types:
    vals = np.array(lut_stack[lt])
    ax1.bar(x, vals, width, bottom=bottom, label=lt, color=colors[lt], edgecolor="black", linewidth=0.6)
    bottom += vals

ax1.set_ylabel("Total LUT Utilization (Count)", fontsize=11, fontweight="bold")
ax1.set_xticks(x)
ax1.set_xticklabels(labels_4x4, fontsize=9.5, fontweight="medium")
ax1.set_ylim(0, 4200)
ax1.set_title("A: 4x4 Core Look-Up Table (LUT) Pruning Breakdown", fontsize=12, fontweight="bold", pad=12)
ax1.grid(axis="y", linestyle="--", alpha=0.4)

for i, (tot, red) in enumerate(zip(total_luts_4x4, lut_red_4x4)):
    txt = f"{tot:,}" + (f"\n(-{red:.1f}%)" if red > 0 else "")
    ax1.annotate(txt, (x[i], tot + 60), ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#084081")

ax1.legend(loc="upper right", ncol=3, framealpha=0.9, fontsize=8.5)

# -------------------------------------------------------------
# Panel B: Flip-Flop & CARRY4 Chain Elimination
# -------------------------------------------------------------
ax2 = axes[0, 1]
width_b = 0.38

bars_ff = ax2.bar(x - width_b/2, ffs_4x4, width_b, label="Flip-Flops (FDCE/FDPE)", color="#2ca02c", alpha=0.88, edgecolor="black", linewidth=0.8)
ax2.set_ylabel("Register Flip-Flop Count", color="#1b7837", fontsize=11, fontweight="bold")
ax2.tick_params(axis="y", labelcolor="#1b7837")
ax2.set_ylim(1400, 2150)

ax2_twin = ax2.twinx()
bars_carry = ax2_twin.bar(x + width_b/2, carry4_4x4, width_b, label="CARRY4 Primitives", color="#d95f02", alpha=0.88, edgecolor="black", linewidth=0.8)
ax2_twin.set_ylabel("CARRY4 Fast-Carry Chains", color="#a63603", fontsize=11, fontweight="bold")
ax2_twin.tick_params(axis="y", labelcolor="#a63603")
ax2_twin.set_ylim(140, 225)

ax2.set_xticks(x)
ax2.set_xticklabels(labels_4x4, fontsize=9.5, fontweight="medium")
ax2.set_title("B: Sequential Register & Carry Chain Pruning", fontsize=12, fontweight="bold", pad=12)
ax2.grid(axis="y", linestyle="--", alpha=0.4)

for b, s_ff in zip(bars_ff, ff_saved_4x4):
    h = b.get_height()
    txt = f"{h:,}" + (f"\n(-{s_ff})" if s_ff > 0 else "")
    ax2.annotate(txt, (b.get_x() + b.get_width()/2, h + 15), ha="center", va="bottom", fontsize=8, fontweight="bold", color="#1b7837")

for b, s_c in zip(bars_carry, carry_saved_4x4):
    h = b.get_height()
    txt = f"{h}" + (f"\n(-{s_c})" if s_c > 0 else "")
    ax2_twin.annotate(txt, (b.get_x() + b.get_width()/2, h + 2), ha="center", va="bottom", fontsize=8, fontweight="bold", color="#a63603")

lines_b1, labs_b1 = ax2.get_legend_handles_labels()
lines_b2, labs_b2 = ax2_twin.get_legend_handles_labels()
ax2.legend(lines_b1 + lines_b2, labs_b1 + labs_b2, loc="upper right", framealpha=0.9, fontsize=8.5)

# -------------------------------------------------------------
# Panel C: Multi-PE Array Scaling on Artix-7 (16 PEs vs 64 PEs)
# -------------------------------------------------------------
ax3 = axes[1, 0]
scale_names = ["4x4 Tensor Core\n(16 PEs, LSB=4)", "8x8 Tensor Core\n(64 PEs, LSB=4)"]
luts_saved_scale = [122, 514]
ffs_saved_scale = [178, 738]
carry_saved_scale = [16, 64]

xs = np.arange(len(scale_names))
w_s = 0.26

ax3.bar(xs - w_s, luts_saved_scale, w_s, label="LUTs Saved", color="#0868ac", alpha=0.9, edgecolor="black", linewidth=0.8)
ax3.bar(xs, ffs_saved_scale, w_s, label="Flip-Flops Saved", color="#2ca02c", alpha=0.9, edgecolor="black", linewidth=0.8)
ax3.bar(xs + w_s, [c * 10 for c in carry_saved_scale], w_s, label="CARRY4 Chains Saved (x10)", color="#d95f02", alpha=0.9, edgecolor="black", linewidth=0.8)

ax3.set_ylabel("FPGA Resources Eliminated", fontsize=11, fontweight="bold")
ax3.set_xticks(xs)
ax3.set_xticklabels(scale_names, fontsize=10, fontweight="bold")
ax3.set_ylim(0, 900)
ax3.set_title("C: Multi-PE Array Compounding on Xilinx 7-Series", fontsize=12, fontweight="bold", pad=12)
ax3.grid(axis="y", linestyle="--", alpha=0.4)

ax3.annotate("122 LUTs", (xs[0] - w_s, 122 + 20), ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#0868ac")
ax3.annotate("178 FFs", (xs[0], 178 + 20), ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#2ca02c")
ax3.annotate("16 C4", (xs[0] + w_s, 160 + 20), ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#d95f02")

ax3.annotate("514 LUTs", (xs[1] - w_s, 514 + 20), ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#0868ac")
ax3.annotate("738 FFs", (xs[1], 738 + 20), ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#2ca02c")
ax3.annotate("64 C4", (xs[1] + w_s, 640 + 20), ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#d95f02")

ax3.legend(loc="upper left", framealpha=0.9, fontsize=9)

# -------------------------------------------------------------
# Panel D: Artix-7 XC7A35T Device Footprint vs Accuracy Pareto
# -------------------------------------------------------------
ax4 = axes[1, 1]

# Plot Pareto curve
sc = ax4.scatter(frob_err_4x4[1:], artix_util_4x4[1:], c=lut_red_4x4[1:], cmap="plasma_r", s=140, edgecolors="black", linewidth=1.2, zorder=5)
cbar = plt.colorbar(sc, ax=ax4)
cbar.set_label("FPGA LUT Reduction (%)", fontsize=10, fontweight="bold")

ax4.plot(frob_err_4x4, artix_util_4x4, linestyle="--", color="#444444", alpha=0.7, zorder=3)

# Sweet spot highlight
ax4.axvspan(-0.1, 1.2, color="#2ca02c", alpha=0.12, label="High-Fidelity Inference Zone (< 1.2% Err)")
ax4.axvline(1.2, color="#2ca02c", linestyle=":", linewidth=1.5)

cfg_tags = ["Light (LSB=2)", "Conserv. (LSB=4)", "Moderate (LSB=6)", "Aggress. (LSB=8)"]
offsets = [(0.15, 0.2), (0.2, -0.3), (0.2, 0.2), (-1.4, 0.2)]
for i, tag in enumerate(cfg_tags):
    fx = frob_err_4x4[i+1]
    fy = artix_util_4x4[i+1]
    ox, oy = offsets[i]
    ax4.annotate(
        f"{tag}\nErr: {fx:.2f}% | Util: {fy:.1f}%",
        xy=(fx, fy),
        xytext=(fx + ox, fy + oy),
        arrowprops=dict(arrowstyle="->", color="black", lw=1.0),
        fontsize=8.5,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#cccccc", alpha=0.9)
    )

# Exact baseline marker
ax4.scatter([frob_err_4x4[0]], [artix_util_4x4[0]], color="black", s=100, zorder=6, label="Exact Baseline (16.7%)")

ax4.set_xlabel("Frobenius Norm Relative Error on Matrix Product (%)", fontsize=11, fontweight="bold")
ax4.set_ylabel("Artix-7 XC7A35T Total LUT Utilization (%)", fontsize=11, fontweight="bold")
ax4.set_title("D: Matrix Accuracy vs Artix-7 Chip Utilization Pareto Frontier", fontsize=12, fontweight="bold", pad=12)
ax4.grid(True, linestyle="--", alpha=0.4)
ax4.set_xlim(-0.2, 5.5)
ax4.set_ylim(15.0, 17.2)
ax4.legend(loc="upper right", framealpha=0.9, fontsize=9)

plt.suptitle(
    "AxSYS Attribute-Driven Approximate Computing Flow: Complete FPGA Evaluation\n"
    "Target Device: Xilinx Artix-7 (XC7A35T / XC7A100T) via Yosys synth_xilinx -family xc7",
    fontsize=14,
    fontweight="bold",
    y=0.99
)

plt.tight_layout(rect=[0, 0.02, 1, 0.96])
plt.savefig(OUTPUT_PNG, dpi=300)
plt.close()
print(f"FPGA Artix-7 visual dashboard saved to: {OUTPUT_PNG}")
