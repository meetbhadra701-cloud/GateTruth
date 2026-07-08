# toy_task — cocotb smoke test (NON-SCORED harness fixture)
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

WIDTH = 4
MASK = (1 << WIDTH) - 1


@cocotb.test()
async def toy_increment(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    # Synchronous, active-high reset -> y == 0.
    dut.a.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await Timer(1, units="ns")
    assert int(dut.y.value) == 0, f"y should be 0 after reset, got {int(dut.y.value)}"

    # y follows a + 1 (registered).
    for a in range(1 << WIDTH):
        dut.a.value = a
        await RisingEdge(dut.clk)
        await Timer(1, units="ns")
        assert int(dut.y.value) == ((a + 1) & MASK), (
            f"a={a}: expected y={(a + 1) & MASK}, got {int(dut.y.value)}"
        )
