"""Shared test hygiene: release matplotlib figures after each test (analyses build figures in memory)."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")
