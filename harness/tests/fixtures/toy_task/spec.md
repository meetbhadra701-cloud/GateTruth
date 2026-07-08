# toy_task — harness test fixture (NON-SCORED)

This is **not** a benchmark task. It is a minimal, deterministic fixture used by SB-003 (stages 0–2)
and SB-007 (stages 3–5) to exercise the harness pipeline without depending on the real pilot tasks.
It lives under `harness/tests/fixtures/` and is **never** part of the 60-task suite or any leaderboard.

Design: a `WIDTH`-bit register that outputs `a + 1` each clock, cleared to `0` by synchronous,
active-high reset. Chosen because it lints clean, simulates trivially, synthesizes to a handful of
sky130hd cells, and presents both a register-to-output and an input-to-register path for STA/power.

Interface: `clk`, `rst` (sync, active-high), `a[WIDTH-1:0]` in; `y[WIDTH-1:0]` out.
