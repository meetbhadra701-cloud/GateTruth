An SPI master in mode 0 (CPOL=0, CPHA=0) requires careful sequencing of the chip select (`cs_n`), serial clock (`sclk`), and master-out data (`mosi`) signals. This implementation uses a finite state machine (FSM) with two main states: `IDLE` and `TRANSFER`.

In the `IDLE` state, the module waits for a `start` signal. All outputs are held in their inactive states: `cs_n` is high, `sclk` is low, and `busy` is low.

Upon receiving a `start` request while not `busy`, the FSM transitions to the `TRANSFER` state. On this transition, `busy` and `cs_n` are asserted, the `
