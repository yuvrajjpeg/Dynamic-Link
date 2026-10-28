#!/bin/zsh
# Builds dist/Dynamic Bridge.pkg: a standard macOS Installer package for the bridge.
set -e
cd -- "${0:A:h}/.."
work=$(mktemp -d)
payload="$work/root/Library/Application Support/Dynamic Bridge"
mkdir -p "$payload" dist
COPYFILE_DISABLE=1 cp -R install.py README.md resolve_ae resolve_lua scripts "$payload/"
find "$work/root" -name __pycache__ -prune -exec rm -rf {} +
xattr -cr "$work/root"
COPYFILE_DISABLE=1 pkgbuild --quiet --root "$work/root" --scripts packaging/scripts \
    --identifier com.dynamicbridge.plugin --version 0.1.3 --install-location / \
    "$work/DynamicBridge-component.pkg"
COPYFILE_DISABLE=1 productbuild --quiet --distribution packaging/distribution.xml --resources packaging/resources \
    --package-path "$work" "dist/Dynamic Bridge.pkg"
rm -rf "$work"
echo "Built dist/Dynamic Bridge.pkg"

# Windows installer, when NSIS is available (brew install makensis).
if command -v makensis >/dev/null 2>&1; then
    makensis -V2 packaging/windows/installer.nsi
    echo "Built dist/Dynamic Bridge Setup.exe"
fi
