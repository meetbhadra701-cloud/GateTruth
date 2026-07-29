# External Mutation Audit Summary

Generated from the committed per-design JSON reports. Counts and kill rates
below are not entered by hand.

## RTLLM

- Seed: `20260729`
- Designs reported: 50
- Audited: 44
- Unsupported: 6
- Mutants: 751
- Killed: 418
- Survived: 318
- Indeterminate: 15
- Aggregate kill fraction: 418/751
- Determinism sample (8): `multi_16bit`, `multi_pipe_8bit`, `freq_divbyfrac`, `barrel_shifter`, `edge_detect`, `comparator_4bit`, `alu`, `signal_generator`
- Determinism result: byte-identical per-design JSON

### Per-design results

| Design | Status | Mutants | Killed | Survived | Indeterminate | Kill rate (%) | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| JC_counter | audited | 3 | 3 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_JC_counter -> JC_counter |
| LFSR | audited | 5 | 5 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 |
| LIFObuffer | audited | 26 | 18 | 8 | 0 | 69.2308 | baseline passed under Icarus Verilog-2001 |
| RAM | audited | 5 | 3 | 2 | 0 | 60.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_RAM -> RAM |
| ROM | audited | 5 | 5 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 |
| accu | audited | 22 | 15 | 7 | 0 | 68.1818 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_accu -> accu |
| adder_16bit | audited | 8 | 2 | 6 | 0 | 25.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_adder_16bit -> adder_16bit |
| adder_32bit | audited | 46 | 21 | 25 | 0 | 45.6522 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_adder_32bit -> adder_32bit |
| adder_8bit | audited | 1 | 0 | 1 | 0 | 0.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_adder_8bit -> adder_8bit |
| adder_bcd | audited | 5 | 5 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 |
| adder_pipe_64bit | audited | 62 | 32 | 26 | 4 | 51.6129 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_adder_64bit -> adder_pipe_64bit |
| alu | audited | 53 | 35 | 18 | 0 | 66.0377 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_alu -> alu |
| asyn_fifo | unsupported | 0 | 0 | 0 | 0 | 0.0 | Icarus compile failed (exit 1): <vendor>/Memory/FIFO/asyn_fifo/testbench.v:102: error: Enable of unknown task ``break''. \| 1 error(s) during elaboration. |
| barrel_shifter | audited | 1 | 1 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 |
| calendar | audited | 12 | 11 | 1 | 0 | 91.6667 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_calendar -> calendar |
| clkgenerator | unsupported | 0 | 0 | 0 | 0 | 0.0 | Icarus compile failed (exit 2): <vendor>/Miscellaneous/RISC-V/clkgenerator/testbench.v:8: error: Output port expression must support continuous assignment. \| <vendor>/Miscellaneous/RISC-V/clkgenerator/testbench.v:8:      : Port 1 (clk) of clkgenerator is connected to clk_tb \| 2 error(s) during elaboration. |
| comparator_3bit | audited | 4 | 4 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 |
| comparator_4bit | audited | 6 | 5 | 1 | 0 | 83.3333 | baseline passed under Icarus Verilog-2001 |
| counter_12 | audited | 4 | 3 | 1 | 0 | 75.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_counter_12 -> counter_12 |
| div_16bit | audited | 10 | 10 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_div_16bit -> div_16bit |
| edge_detect | audited | 10 | 0 | 10 | 0 | 0.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_edge_detect -> edge_detect |
| fixed_point_adder | audited | 20 | 1 | 19 | 0 | 5.0 | baseline passed under Icarus Verilog-2001 |
| fixed_point_substractor | audited | 20 | 1 | 19 | 0 | 5.0 | baseline passed under Icarus Verilog-2001 |
| float_multi | audited | 115 | 33 | 82 | 0 | 28.6957 | baseline passed under Icarus Verilog-2001 |
| freq_div | audited | 12 | 12 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 |
| freq_divbyeven | audited | 7 | 7 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 |
| freq_divbyfrac | audited | 20 | 18 | 2 | 0 | 90.0 | baseline passed under Icarus Verilog-2001 |
| freq_divbyodd | unsupported | 0 | 0 | 0 | 0 | 0.0 | Icarus compile failed (exit 1): <vendor>/Miscellaneous/Frequency divider/freq_divbyodd/verified_freq_divbyodd.v:48: error: reg clk_div; cannot be driven by primitives or continuous assignment. \| 1 error(s) during elaboration. |
| fsm | audited | 26 | 19 | 7 | 0 | 73.0769 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_fsm -> fsm |
| instr_reg | audited | 8 | 6 | 2 | 0 | 75.0 | baseline passed under Icarus Verilog-2001 |
| multi_16bit | audited | 21 | 14 | 7 | 0 | 66.6667 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_multi_16bit -> multi_16bit |
| multi_8bit | unsupported | 0 | 0 | 0 | 0 | 0.0 | Icarus compile failed (exit 2): <vendor>/Arithmetic/Multiplier/multi_8bit/verified_multi_8bit.v:15: syntax error \| <vendor>/Arithmetic/Multiplier/multi_8bit/verified_multi_8bit.v:15: error: Incomprehensible for loop. |
| multi_booth_8bit | audited | 11 | 9 | 0 | 2 | 81.8182 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_multi_booth_8bit -> multi_booth_8bit |
| multi_pipe_4bit | audited | 12 | 9 | 3 | 0 | 75.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_multi_pipe -> multi_pipe_4bit |
| multi_pipe_8bit | audited | 30 | 17 | 11 | 2 | 56.6667 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_multi_pipe_8bit -> multi_pipe_8bit |
| parallel2serial | audited | 13 | 7 | 3 | 3 | 53.8462 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_parallel2serial -> parallel2serial |
| pe | audited | 3 | 3 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_pe -> pe |
| pulse_detect | audited | 24 | 21 | 3 | 0 | 87.5 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_pulse_detect -> pulse_detect |
| radix2_div | unsupported | 0 | 0 | 0 | 0 | 0.0 | simulation emitted no recognized pass banner: Error: dividend=123, divisor=123, expected=0001, got=6400 \| ===========Failed===========          3 \| <vendor>/Arithmetic/Divider/radix2_div/testbench.v:87: $finish called at 825000 (1ps) |
| right_shifter | audited | 4 | 3 | 1 | 0 | 75.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_right_shifter -> right_shifter |
| ring_counter | unsupported | 0 | 0 | 0 | 0 | 0.0 | Icarus compile failed (exit 1): <vendor>/Control/Counter/ring_counter/verified_ring_counter.v:19: error: reg out; cannot be driven by primitives or continuous assignment. \| <vendor>/Control/Counter/ring_counter/testbench.v:20: error: Assignment to an entire array or to an array slice requires SystemVerilog. \| Elaboration failed |
| sequence_detector | audited | 15 | 7 | 8 | 0 | 46.6667 | baseline passed under Icarus Verilog-2001 |
| serial2parallel | audited | 13 | 4 | 5 | 4 | 30.7692 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_serial2parallel -> serial2parallel |
| signal_generator | audited | 8 | 8 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_signal_generator -> signal_generator |
| square_wave | audited | 6 | 0 | 6 | 0 | 0.0 | baseline passed under Icarus Verilog-2001 |
| sub_64bit | audited | 6 | 1 | 5 | 0 | 16.6667 | baseline passed under Icarus Verilog-2001 |
| synchronizer | audited | 10 | 5 | 5 | 0 | 50.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_synchronizer -> synchronizer |
| traffic_light | audited | 40 | 22 | 18 | 0 | 55.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_traffic_light -> traffic_light |
| up_down_counter | audited | 7 | 7 | 0 | 0 | 100.0 | baseline passed under Icarus Verilog-2001 |
| width_8to16 | audited | 12 | 6 | 6 | 0 | 50.0 | baseline passed under Icarus Verilog-2001 after temporary module alias verified_width_8to16 -> width_8to16 |

## CVDP

- Rows inspected: 302
- Rows with usable golden RTL: 0
- Rows with withheld outputs: 302
- Result: no mutation-kill audit; see `results/cvdp/FINDING.md`.
