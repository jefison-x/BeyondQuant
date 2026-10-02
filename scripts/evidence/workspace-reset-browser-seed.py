#!/usr/bin/env python3
"""Create a dedicated ordinary identity for a successful CI Reset browser case."""
import os
from tests.workspace_helpers import trusted_agent_context

if os.environ.get("BYQ_RESET_BROWSER_FIXTURE") != "1":
    raise SystemExit("explicit isolated CI fixture invocation required")
trusted_agent_context("phase17-reset-browser")
print("Dedicated ordinary-user Reset fixture prepared; no model or market calls.")
