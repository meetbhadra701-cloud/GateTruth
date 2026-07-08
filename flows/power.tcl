# SB-007 OpenSTA deterministic default-activity power template.
read_liberty $::env(SB_LIBERTY)
read_verilog $::env(SB_NETLIST)
link_design $::env(SB_TOP)
read_sdc $::env(SB_CONSTRAINTS)
report_power -digits 8
