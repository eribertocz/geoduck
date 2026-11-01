#!/usr/bin/env bash
# F-03: PyArrow 26.0.0 no importa con NumPy 1.26.4; 25.0.1 sí.
# Requiere un Python con numpy==1.26.4 (p. ej. python3-numpy de Ubuntu 24.04).
set -u
for pa in 26.0.0 25.0.1; do
  python3 -m venv --system-site-packages "/tmp/pa_$pa" >/dev/null
  "/tmp/pa_$pa/bin/pip" install -q "pyarrow==$pa"
  printf 'pyarrow %s: ' "$pa"
  "/tmp/pa_$pa/bin/python" -c "import numpy, pyarrow; print('OK con numpy', numpy.__version__)" 2>&1 | tail -1
done
