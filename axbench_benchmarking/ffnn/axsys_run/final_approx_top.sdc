# =====================================================================
# Auto-generated Attribute-Driven SDC Timing Constraints
# Top Module: ffnn
# Clock: clk @ 5.00 ns
# =====================================================================

# 1. Primary Clock Definition
create_clock -name clk -period 5.000 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks clk]

# 2. Default I/O Timing Delays (30% input, 30% output budgets)
set_input_delay [expr {5.000 * 0.30}] -clock clk [all_inputs -no_clocks]
set_output_delay [expr {5.000 * 0.30}] -clock clk [all_outputs]

# 3. Attribute-Driven Approximate Timing Relaxation
# Relaxed Output Signal: out_act (width=16, relaxed_lsbs=4)
# Metric: MED | Bound: 8.0
set_max_delay 7.500 -to [get_ports {out_act[0]}]
set_max_delay 7.500 -to [get_ports {out_act[1]}]
set_max_delay 7.500 -to [get_ports {out_act[2]}]
set_max_delay 7.500 -to [get_ports {out_act[3]}]

