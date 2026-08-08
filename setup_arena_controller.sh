#!/bin/bash
# Arena Controller Setup Script for Raspberry Pi 4
# Run with: bash setup_arena_controller.sh

set -e

echo "======================================"
echo "Arena Controller Setup for RPi 4"
echo "======================================"

ARCH="$(uname -m)"
if grep -qiE 'Raspberry Pi|BCM' /proc/cpuinfo 2>/dev/null; then
    IS_REAL_PI=1
else
    IS_REAL_PI=0
fi

# Update system
echo "[1/5] Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install dependencies
echo "[2/5] Installing system dependencies..."
sudo apt-get install -y python3-pip python3-dev python3-venv git \
    build-essential gcc-arm-linux-gnueabihf \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev

# Try to install Python 3.11 for better compatibility with RPi.GPIO and pygame
echo "Checking Python version compatibility..."
PYTHON_CMD="python3"
if ! command -v python3.11 >/dev/null 2>&1; then
    echo "Python 3.11 not found, attempting to install..."
    sudo apt-get install -y python3.11 python3.11-venv python3.11-dev 2>/dev/null || {
        echo "Python 3.11 installation failed, falling back to system python3"
        PYTHON_CMD="python3"
    }
else
    PYTHON_CMD="python3.11"
fi
echo "Using Python command: $PYTHON_CMD"

# Enable SPI (real Raspberry Pi only)
echo "[3/5] Configuring hardware interfaces..."
if [ "$IS_REAL_PI" -eq 1 ] && command -v raspi-config >/dev/null 2>&1; then
    sudo raspi-config nonint do_spi 0
else
    echo "Non-RPi or emulator detected (${ARCH}); skipping SPI enable."
fi

# Create virtual environment
echo "[4/5] Setting up Python virtual environment..."

# Aggressively clean up old venv and system cache
if [ -d "arena_env" ]; then
    echo "Removing old virtual environment..."
    rm -rf arena_env
fi

# Clear both user and system pip caches
pip cache purge 2>/dev/null || true
rm -rf ~/.cache/pip 2>/dev/null || true

# Create fresh virtual environment
if [ -z "$PYTHON_CMD" ]; then
    PYTHON_CMD="python3"
fi

if $PYTHON_CMD -m venv arena_env; then
    echo "Virtual environment created successfully"
else
    echo "Failed to create venv with $PYTHON_CMD, trying python3..."
    python3 -m venv arena_env
fi
source arena_env/bin/activate
pip install --upgrade pip --no-cache-dir

# Install Python packages
echo "[5/5] Installing Python packages..."

if [ "$IS_REAL_PI" -eq 1 ]; then
    REQUIREMENTS_FILE="REQUIREMENTS_RPI.txt"
else
    REQUIREMENTS_FILE="REQUIREMENTS_EMULATOR.txt"
fi

echo "Using requirements file: ${REQUIREMENTS_FILE}"

# Install pygame separately with fallback versions to avoid conflicts
echo "Installing pygame with fallback logic..."
pip install --no-cache-dir pygame 2>/dev/null || \
pip install --no-cache-dir pygame==2.5.0 2>/dev/null || \
pip install --no-cache-dir pygame==2.4.0 2>/dev/null || \
pip install --no-cache-dir pygame==2.3.0 2>/dev/null || \
echo "Warning: pygame installation may have issues"

# For real Pi: install RPi.GPIO separately with fallback versions
if [ "$IS_REAL_PI" -eq 1 ]; then
    echo "Installing RPi.GPIO with fallback logic..."
    pip install --no-cache-dir RPi.GPIO 2>/dev/null || \
    pip install --no-cache-dir RPi.GPIO==0.7.1 2>/dev/null || \
    pip install --no-cache-dir RPi.GPIO==0.7.2 2>/dev/null || \
    echo "Warning: RPi.GPIO installation may have issues"
fi

# Install remaining requirements (without pygame and RPi.GPIO)
echo "Installing other dependencies..."
pip install --no-cache-dir -r "${REQUIREMENTS_FILE}"

echo ""
echo "======================================"
echo "Setup Complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Update audio file paths in arena_controller_rpi.py"
echo "2. Verify GPIO pin connections"
echo "3. Run: python3 arena_controller_rpi.py"
echo ""
