"""Image-level compatibility alias: ``healthverse`` -> ``chi_bench``.

The published actava/chi-bench dataset (tag ``chi-bench-v1.0.0``) invokes the
verifier as ``python -m healthverse.verifier.task_runtime`` (and marathon's
``...session_verifier``), and each task's ``tests/test.sh`` states the shared
verifier logic "lives in the packaged healthverse module inside the main
container image". The package was renamed ``healthverse`` -> ``chi_bench`` in
``src/`` without republishing the dataset, which makes the in-sandbox verifier
fail with ``ModuleNotFoundError: No module named 'healthverse'``.

This shim re-points ``healthverse`` at the installed ``chi_bench`` package: its
``__path__`` is chi_bench's, so ``healthverse.verifier.<mod>`` loads
``chi_bench/verifier/<mod>.py``. It is baked into the Docker/Modal image only
(the host code keeps the clean ``chi_bench`` name). Remove once the dataset is
regenerated under the ``chi_bench`` module name.
"""

from __future__ import annotations

import chi_bench as _chi_bench

# Submodule search path = chi_bench's, so healthverse.verifier.task_runtime
# resolves to chi_bench/verifier/task_runtime.py.
__path__ = list(_chi_bench.__path__)
