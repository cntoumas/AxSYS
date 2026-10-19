# =====================================================================
# Auto-generated Attribute-Driven SDC Timing Constraints
# Top Module: fir
# Clock: clk @ 5.00 ns
# =====================================================================

# 1. Primary Clock Definition
create_clock -name clk -period 5.000 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks clk]

# 2. Default I/O Timing Delays (30% input, 30% output budgets)
set_input_delay [expr {5.000 * 0.30}] -clock clk [all_inputs -no_clocks]
set_output_delay [expr {5.000 * 0.30}] -clock clk [all_outputs]

# 3. Attribute-Driven Approximate Timing Relaxation
# Relaxed Output Signal: y_out (width=18, relaxed_lsbs=5)
# Metric: MED | Bound: 16.0
set_max_delay 7.500 -to [get_ports {y_out[0]}]
set_max_delay 7.500 -to [get_ports {y_out[1]}]
set_max_delay 7.500 -to [get_ports {y_out[2]}]
set_max_delay 7.500 -to [get_ports {y_out[3]}]
set_max_delay 7.500 -to [get_ports {y_out[4]}]

