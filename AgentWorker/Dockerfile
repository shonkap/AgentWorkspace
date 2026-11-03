FROM debian:bookworm-slim

# System deps: PlatformIO needs Python; dfu-util for USB DFU flashing;
# usbutils for lsusb debugging; udev for device permission handling inside container.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        dfu-util \
        usbutils \
        udev \
        git \
        curl \
        ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install PlatformIO core into an isolated venv so it doesn't fight system python.
ENV PLATFORMIO_CORE_DIR=/opt/platformio
RUN python3 -m venv /opt/pio-venv \
    && /opt/pio-venv/bin/pip install --no-cache-dir -U platformio
ENV PATH="/opt/pio-venv/bin:${PATH}"
# Debian's /etc/profile unconditionally rewrites PATH for login shells (e.g. VS Code's
# default integrated terminal), which would otherwise drop the venv from PATH.
RUN echo 'export PATH="/opt/pio-venv/bin:${PATH}"' > /etc/profile.d/platformio.sh