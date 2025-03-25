#!/bin/bash

# Check if script is run with sudo
if [ "$EUID" -eq 0 ]; then
    echo "Please run this script as a normal user, not as root"
    exit 1
fi

install() {
    echo "Installing Nova ChatMix..."

    # Install python requirements
    sudo python3 -m pip install pulsectl

    # Create directory and copy script
    mkdir -p "$HOME/.local/bin"
    cp nova.py "$HOME/.local/bin/"

    # Install udev rules
    sudo cp 50-nova-pro-wireless.rules /etc/udev/rules.d/
    sudo udevadm control --reload-rules
    sudo udevadm trigger

    # Install systemd service
    mkdir -p "$HOME/.config/systemd/user"
    cp ./nova-chatmix.service "$HOME/.config/systemd/user/"

    # Enable and start service
    systemctl --user daemon-reload
    systemctl --user enable --now nova-chatmix

    echo "Installation completed!"
}

uninstall() {
    echo "Uninstalling Nova ChatMix..."

    # Stop and disable service
    systemctl --user disable --now nova-chatmix

    # Remove files
    rm -f "$HOME/.local/bin/nova.py"
    rm -f "$HOME/.config/systemd/user/nova-chatmix.service"
    sudo rm -f /etc/udev/rules.d/50-nova-pro-wireless.rules

    # Reload udev
    sudo udevadm control --reload-rules
    sudo udevadm trigger

    echo "Uninstallation completed!"
}

case "$1" in
    "install")
        install
        ;;
    "uninstall")
        uninstall
        ;;
    *)
        echo "Usage: $0 {install|uninstall}"
        exit 1
        ;;
esac
