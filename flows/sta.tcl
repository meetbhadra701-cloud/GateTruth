# SB-007 OpenSTA timing template.
read_liberty $::env(SB_LIBERTY)
read_verilog $::env(SB_NETLIST)
link_design $::env(SB_TOP)
read_sdc $::env(SB_CONSTRAINTS)
set wns [sta::worst_slack -max]
set tns [sta::total_negative_slack -max]
puts "SB_WNS_NS $wns"
puts "SB_TNS_NS $tns"
report_checks -path_delay max -fields {slew cap input_pins} -digits 8
