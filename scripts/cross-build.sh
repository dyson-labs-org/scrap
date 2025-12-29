#!/bin/bash
# SCAP Cross-Compilation Build Script
#
# Builds SCAP libraries for various satellite processor architectures.
#
# Usage:
#   ./scripts/cross-build.sh [target] [options]
#
# Targets:
#   arm64       - ARM64 Linux (aarch64-unknown-linux-gnu)
#   arm64-musl  - ARM64 Linux with musl (static linking)
#   arm32       - ARM32 Linux (armv7-unknown-linux-gnueabihf)
#   cortex-m4   - Bare metal Cortex-M4F (scap-core only)
#   cortex-m3   - Bare metal Cortex-M3 (scap-core only)
#   all         - Build all targets
#   native      - Build for host architecture
#
# Options:
#   --install-deps  Install cross-compilation toolchains
#   --use-cross     Use 'cross' tool instead of native toolchain
#   --debug         Build with debug symbols
#   --check         Only check compilation, don't produce binaries

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$PROJECT_DIR/target/cross"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

install_deps() {
    log_info "Installing cross-compilation dependencies..."

    if command -v pacman &> /dev/null; then
        log_info "Detected Arch Linux, installing via pacman..."
        sudo pacman -S --needed --noconfirm \
            aarch64-linux-gnu-gcc \
            arm-none-eabi-gcc \
            arm-none-eabi-newlib \
            arm-none-linux-gnueabihf-gcc 2>/dev/null || true
    elif command -v apt-get &> /dev/null; then
        log_info "Detected Debian/Ubuntu, installing via apt..."
        sudo apt-get update
        sudo apt-get install -y \
            gcc-aarch64-linux-gnu \
            gcc-arm-none-eabi \
            libnewlib-arm-none-eabi \
            gcc-arm-linux-gnueabihf
    else
        log_warn "Unknown package manager. Install toolchains manually or use --use-cross"
    fi

    log_info "Installing Rust targets..."
    rustup target add aarch64-unknown-linux-gnu
    rustup target add aarch64-unknown-linux-musl
    rustup target add armv7-unknown-linux-gnueabihf
    rustup target add arm-unknown-linux-gnueabihf
    rustup target add thumbv7em-none-eabihf
    rustup target add thumbv7m-none-eabi
    rustup target add thumbv6m-none-eabi

    log_info "Dependencies installed."
}

build_target() {
    local target="$1"
    local profile="${2:-release}"
    local extra_args="${3:-}"
    local crates="${4:-}"

    log_info "Building for target: $target"

    local cargo_cmd="cargo build --target $target"

    if [[ "$profile" == "release" ]]; then
        cargo_cmd+=" --release"
    fi

    if [[ -n "$crates" ]]; then
        cargo_cmd+=" -p $crates"
    fi

    if [[ -n "$extra_args" ]]; then
        cargo_cmd+=" $extra_args"
    fi

    log_info "Running: $cargo_cmd"
    cd "$PROJECT_DIR"
    eval "$cargo_cmd"

    local target_dir="$PROJECT_DIR/target/$target/$profile"
    if [[ -d "$target_dir" ]]; then
        mkdir -p "$OUTPUT_DIR/$target"

        if [[ -f "$target_dir/libscap_core.a" ]]; then
            cp "$target_dir/libscap_core.a" "$OUTPUT_DIR/$target/"
            log_info "  -> libscap_core.a"
        fi
        if [[ -f "$target_dir/libscap_ffi.a" ]]; then
            cp "$target_dir/libscap_ffi.a" "$OUTPUT_DIR/$target/"
            log_info "  -> libscap_ffi.a"
        fi
        if [[ -f "$target_dir/libscap_ffi.so" ]]; then
            cp "$target_dir/libscap_ffi.so" "$OUTPUT_DIR/$target/"
            log_info "  -> libscap_ffi.so"
        fi
    fi
}

build_with_cross() {
    local target="$1"
    local profile="${2:-release}"

    if ! command -v cross &> /dev/null; then
        log_info "Installing 'cross' tool..."
        cargo install cross
    fi

    log_info "Building for $target using cross..."
    cd "$PROJECT_DIR"

    local cmd="cross build --target $target"
    if [[ "$profile" == "release" ]]; then
        cmd+=" --release"
    fi

    eval "$cmd"
}

show_sizes() {
    log_info "Binary sizes:"
    if [[ -d "$OUTPUT_DIR" ]]; then
        find "$OUTPUT_DIR" -type f \( -name "*.a" -o -name "*.so" \) -exec ls -lh {} \; | \
            awk '{print "  " $NF ": " $5}'
    fi
}

show_usage() {
    cat << EOF
SCAP Cross-Compilation Build Script

Usage: $0 [target] [options]

Targets:
  arm64       ARM64 Linux (aarch64-unknown-linux-gnu)
  arm64-musl  ARM64 Linux with musl (fully static)
  arm32       ARM32 Linux (armv7-unknown-linux-gnueabihf)
  cortex-m4   Bare metal Cortex-M4F (thumbv7em-none-eabihf)
  cortex-m3   Bare metal Cortex-M3 (thumbv7m-none-eabi)
  all         Build all Linux targets
  native      Build for host architecture

Options:
  --install-deps  Install cross-compilation toolchains
  --use-cross     Use 'cross' tool (Docker-based, no local toolchain needed)
  --debug         Build with debug symbols
  --check         Only check compilation

Examples:
  $0 --install-deps           # Install toolchains first
  $0 arm64                    # Build for ARM64 Linux
  $0 cortex-m4                # Build scap-core for Cortex-M4
  $0 all                      # Build for all targets
  $0 arm64 --use-cross        # Build using cross (Docker)

Output:
  Libraries are placed in target/cross/<target>/
EOF
}

main() {
    local target=""
    local use_cross=false
    local profile="release"
    local check_only=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --install-deps)
                install_deps
                exit 0
                ;;
            --use-cross)
                use_cross=true
                shift
                ;;
            --debug)
                profile="debug"
                shift
                ;;
            --check)
                check_only=true
                shift
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            *)
                target="$1"
                shift
                ;;
        esac
    done

    if [[ -z "$target" ]]; then
        show_usage
        exit 1
    fi

    mkdir -p "$OUTPUT_DIR"

    local extra_args=""
    if [[ "$check_only" == true ]]; then
        extra_args="--check"
    fi

    case "$target" in
        arm64)
            if [[ "$use_cross" == true ]]; then
                build_with_cross "aarch64-unknown-linux-gnu" "$profile"
            else
                build_target "aarch64-unknown-linux-gnu" "$profile" "$extra_args"
            fi
            ;;
        arm64-musl)
            if [[ "$use_cross" == true ]]; then
                build_with_cross "aarch64-unknown-linux-musl" "$profile"
            else
                build_target "aarch64-unknown-linux-musl" "$profile" "$extra_args"
            fi
            ;;
        arm32)
            if [[ "$use_cross" == true ]]; then
                build_with_cross "armv7-unknown-linux-gnueabihf" "$profile"
            else
                build_target "armv7-unknown-linux-gnueabihf" "$profile" "$extra_args"
            fi
            ;;
        cortex-m4)
            build_target "thumbv7em-none-eabihf" "$profile" "$extra_args --no-default-features" "scap-core"
            ;;
        cortex-m3)
            build_target "thumbv7m-none-eabi" "$profile" "$extra_args --no-default-features" "scap-core"
            ;;
        cortex-m0)
            build_target "thumbv6m-none-eabi" "$profile" "$extra_args --no-default-features" "scap-core"
            ;;
        all)
            log_info "Building all targets..."
            if [[ "$use_cross" == true ]]; then
                build_with_cross "aarch64-unknown-linux-gnu" "$profile"
                build_with_cross "armv7-unknown-linux-gnueabihf" "$profile"
            else
                build_target "aarch64-unknown-linux-gnu" "$profile" "$extra_args" || log_warn "ARM64 build failed"
                build_target "armv7-unknown-linux-gnueabihf" "$profile" "$extra_args" || log_warn "ARM32 build failed"
            fi
            build_target "thumbv7em-none-eabihf" "$profile" "$extra_args --no-default-features" "scap-core" || log_warn "Cortex-M4 build failed"
            ;;
        native)
            build_target "$(rustc -vV | grep host | cut -d' ' -f2)" "$profile" "$extra_args"
            ;;
        *)
            log_error "Unknown target: $target"
            show_usage
            exit 1
            ;;
    esac

    if [[ "$check_only" == false ]]; then
        show_sizes
    fi

    log_info "Done!"
}

main "$@"
