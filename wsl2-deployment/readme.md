# Garmin Messenger Media Bridge - WSL2 Installation Guide

A complete guide for running the Garmin Messenger media bridge in WSL2 with Redroid (Android emulation).

## Overview

This setup allows you to run an Android emulator inside WSL2, install Garmin Messenger, and automatically forward media files via email. The solution requires recompiling the WSL2 kernel with Android Binder support or using pre-compiled kernels.

## Prerequisites

- Windows with WSL2 support
- Administrator access
- Basic command line knowledge

## Installation Steps

### 1. Install WSL2 Debian

Open PowerShell and run:

```powershell
wsl.exe --install Debian
```

> **Note:** Ubuntu should also work, but this guide uses Debian. It assumes the username created on debian is in fact debian. If you select another username, you might need to tweak the location of folders inside the docker-compose.yml file.

### 2. Install Docker in WSL2

Inside your WSL2 Debian installation, follow the official Docker installation guide:

[Docker Engine Installation - Debian](https://docs.docker.com/engine/install/debian/)

### 3. Install scrcpy

Install scrcpy using the official installation script:

```bash
wget https://github.com/Genymobile/scrcpy/blob/master/install_release.sh
bash install_release.sh
```

[Official scrcpy repository](https://github.com/Genymobile/scrcpy)

### 4. Install Docker Desktop for Windows

1. Download and install Docker Desktop for Windows
2. In Docker Desktop settings:
   - Enable "Use the WSL 2 based engine" (General settings)
   - Enable "Start Docker Desktop when you sign in"

### 5. Set Up Custom WSL2 Kernel

You need a WSL2 kernel with Android Binder support enabled.

**Option A: Use pre-compiled kernel**

1. Download the `bzImage` and `.vhdx` files from the release section in this repository on your windows computer https://github.com/palchrb/inreach_mediarelay/releases/tag/v6.6.87.2-android
2. Open "WSL Settings" from Windows Start Menu
3. Go to "Developer Settings"
4. Select the `bzImage` file as custom kernel
5. Select the `.vhdx` file as custom kernel modules

**Option B: Compile your own kernel**

Follow this guide: [WSL2 Kernel Compilation with Binder Support](https://gist.github.com/onomatopellan/c5220c0efddaff69aaff77cca80b7b8e)

After setting up the custom kernel, restart WSL2:

```powershell
wsl --shutdown
wsl
```

### 6. Configure WSL2 Boot Settings

Inside WSL2, edit the WSL configuration:

```bash
nano /etc/wsl.conf
```

Add the following under the `[boot]` section:

```ini
command="mkdir -p /dev/binderfs && mount -t binder binder /dev/binderfs && modprobe vgem"
```

Save and exit (Ctrl+X, then Y, then Enter).

Restart WSL2:

```powershell
wsl --shutdown
wsl
```

### 7. Set Up Redroid Container

Clone the repository and navigate to the redroid folder:

```bash
git clone <repository-url>
cd wsl2-deployment/redroid
```

Build and start the containers:

```bash
docker compose build
docker compose up -d
```

> **Important:** Initial startup can take up to 5 minutes. This delay also occurs after each reboot or `wsl --shutdown`.

### 8. Connect ADB

Wait for the container to fully start, then connect via ADB:

```bash
adb connect localhost:5555
adb devices
```

The device should show as "device" (not "offline"). If it shows as offline, wait a few more minutes and retry.

### 9. Launch scrcpy

Once ADB is connected properly, start scrcpy:

```bash
scrcpy -s localhost:5555
```

The Redroid Android interface should appear in a new window.

### 10. Register Device with Google

1. While connected via ADB, visit: [Google Android Uncertified Device Registration](https://www.google.com/android/uncertified)
2. Follow the registration procedure
3. Wait up to 1 hour for registration to complete
4. Restart the container to finalize registration:

```bash
docker compose down
docker compose up -d
```

5. Reconnect scrcpy after the restart

### 11. Install Garmin Messenger

1. Open the Play Store in the Redroid interface
2. Sign in with your Google account
3. Download and install Garmin Messenger
4. Log in with the phone number you want to use as the media relay bridge

### 12. Configure the Bridge

Edit the bridge configuration:

```bash
nano bridge/garmin.env
```

Configure your email settings for media forwarding. The settings are identical to those described in the main repository README.

Restart the containers to apply changes:

```bash
docker compose down
docker compose up -d
```

### 13. Verify Operation

Check the bridge logs to confirm media files are being detected and forwarded:

```bash
docker logs garmin-bridge -f
```

## Troubleshooting

- **Container won't start:** Wait up to 5 minutes for initial startup
- **ADB shows offline:** Wait a few more minutes and retry the connection
- **Registration not working:** Ensure you've waited the full hour after registration
- **Media not forwarding:** Check the bridge logs for errors

## Notes

- Some dependencies may not be explicitly covered in this guide. If you encounter missing dependencies, consult ChatGPT or seek assistance from someone with Linux experience.
- The startup delay after each WSL2 restart is a known issue with unclear cause.

## Support

For issues specific to:
- **Docker:** [Docker Documentation](https://docs.docker.com/)
- **scrcpy:** [scrcpy GitHub Issues](https://github.com/Genymobile/scrcpy/issues)
- **WSL2:** [WSL Documentation](https://docs.microsoft.com/en-us/windows/wsl/)
