"""Exercises SystemStatsSampler against the real running process via psutil
-- not mocked, since psutil.Process() genuinely reflects this test run.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.utils.system_stats import SystemStatsSampler


def test_tick_emits_real_nonnegative_process_stats(qapp):
    sampler = SystemStatsSampler()

    samples = []
    sampler.sample_ready.connect(lambda cpu, ram: samples.append((cpu, ram)))
    sampler._tick()

    assert len(samples) == 1
    cpu_percent, ram_mb = samples[0]
    assert cpu_percent >= 0.0
    assert ram_mb > 0.0  # this process is genuinely using some memory


def test_start_and_stop_control_the_timer(qapp):
    sampler = SystemStatsSampler()
    assert not sampler._timer.isActive()

    sampler.start()
    assert sampler._timer.isActive()

    sampler.stop()
    assert not sampler._timer.isActive()
