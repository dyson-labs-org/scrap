# Portable SCRAP authority package and its cross-language verification.
.PHONY: test-authority wheel-authority
PYTHON ?= python3
WHEEL_DIR ?= dist

test-authority:
	cargo test --locked -p scrap-core -p scrap-ffi
	$(PYTHON) -m unittest discover -s bindings/python/tests

wheel-authority:
	$(PYTHON) -m pip wheel --no-deps --wheel-dir "$(WHEEL_DIR)" .
