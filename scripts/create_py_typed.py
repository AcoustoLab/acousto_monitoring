"""Stub files for nidaqmx."""

import pathlib
import nidaqmx

pkg_dir = pathlib.Path(nidaqmx.__file__).parent
(pkg_dir / "py.typed").touch(exist_ok=True)

print(f"Created: {pkg_dir / 'py.typed'}")
