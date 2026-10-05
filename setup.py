"""Build a platform wheel containing the existing SCRAP FFI; never fetch source at runtime."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from setuptools import setup
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel


class BuildAuthority(build_py):
    """Compile the pinned lockfile and package the native library with its Python caller."""

    def run(self):
        root = Path(__file__).parent.resolve()
        subprocess.run(["cargo", "build", "--release", "--locked", "-p", "scrap-ffi"], cwd=root, check=True)
        super().run()
        suffix = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
        name = "scrap_ffi.dll" if sys.platform == "win32" else "libscrap_ffi" + suffix
        target = Path(os.environ.get("CARGO_TARGET_DIR", root / "target"))
        if not target.is_absolute():
            target = root / target
        shutil.copyfile(target / "release" / name, Path(self.build_lib) / "scrap_authority" / ("scrap_native" + suffix))


class PlatformWheel(bdist_wheel):
    """Mark native wheels as platform-specific while keeping a Python-independent ABI."""

    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self):
        _, _, platform = super().get_tag()
        return "py3", "none", platform


setup(cmdclass={"build_py": BuildAuthority, "bdist_wheel": PlatformWheel})
