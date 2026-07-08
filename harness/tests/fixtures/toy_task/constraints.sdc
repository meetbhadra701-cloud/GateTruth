# toy_task — timing constraints (NON-SCORED harness fixture)
create_clock -name clk -period 10.0 [get_ports clk]
set_input_delay  -clock clk 2.0 [get_ports {rst a}]
set_output_delay -clock clk 2.0 [get_ports y]
