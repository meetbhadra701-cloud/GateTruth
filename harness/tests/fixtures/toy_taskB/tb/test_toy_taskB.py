import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


@cocotb.test()
async def public_smoke_clock_and_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rst.value = 1
    dut.a.value = 0
    dut.b.value = 0
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    dut.a.value = 1
    dut.b.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
