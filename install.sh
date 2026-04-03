#!/bin/bash
# Finance OS — One-line installer (macOS / Linux)
# Usage: curl -sSL <url> | bash  OR  bash install.sh

set -e

echo ""
echo "  Finance OS Installer"
echo "  ====================="
echo "  Local-first personal finance intelligence"
echo ""

# Check Python 3.10+
if ! command -v python3 &> /dev/null; then
    echo "  ERROR: Python 3 is required. Install from https://python.org"
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python $PY_VERSION detected"

# Create install directory
INSTALL_DIR="$HOME/.financeos-app"
echo "  Installing to $INSTALL_DIR"

if [ -d "$INSTALL_DIR" ]; then
    echo "  Updating existing installation..."
else
    mkdir -p "$INSTALL_DIR"
fi

# Copy app files
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp -r "$SCRIPT_DIR"/*.py "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR"/routers "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR"/services "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR"/templates "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR"/static "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR"/samples "$INSTALL_DIR/"
cp "$SCRIPT_DIR"/requirements.txt "$INSTALL_DIR/"

# Create venv and install deps
echo "  Setting up Python environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt" 2>/dev/null

# Create launcher script
cat > "$INSTALL_DIR/launch.sh" << 'LAUNCHER'
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python main.py "$@"
LAUNCHER
chmod +x "$INSTALL_DIR/launch.sh"

# Create convenience symlink
if [ -d "/usr/local/bin" ]; then
    ln -sf "$INSTALL_DIR/launch.sh" /usr/local/bin/financeos 2>/dev/null || true
fi

echo ""
echo "  Installation complete!"
echo ""
echo "  To run:  $INSTALL_DIR/launch.sh"
echo "  Or:      financeos"
echo ""
echo "  Data stored at: ~/.financeos/finance.db"
echo "  100% local. Nothing leaves your machine."
echo ""
