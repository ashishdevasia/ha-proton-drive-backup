ARG BUILD_FROM
FROM $BUILD_FROM

# Provided by the Home Assistant build system (amd64 / aarch64).
ARG BUILD_ARCH
ARG PROTON_CLI_VERSION=0.8.0
# SHA256 of the official CLI binaries for PROTON_CLI_VERSION (per architecture;
# note amd64 pins the linux-x64-BASELINE flavor, see the download step below).
# Proton publishes SHA-512 checksums at https://proton.me/download/drive/cli/index.html;
# these are the SHA256 of the same binaries, pinned here and must be refreshed
# whenever PROTON_CLI_VERSION changes.
ARG PROTON_CLI_SHA256_AMD64=765fd434e7ea53f1f45c823408ad10dfdca60069885a3b577c420e2511775175
ARG PROTON_CLI_SHA256_AARCH64=086bc4740a73cb8eb4900d51836bff0c332dda390b3f0780d9f805fd5c2a5fe3

WORKDIR /app

# System dependencies:
#  - python3 + pip to run the addon
#  - dbus + gnome-keyring + libsecret: the proton-drive CLI stores its session in
#    the OS secret store via libsecret, so we run a Secret Service inside the
#    container (see run.sh).
#  - ca-certificates/curl to fetch the CLI.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        dbus gnome-keyring libsecret-1-0 \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Download the Proton Drive CLI binary for this architecture and verify it
# against the pinned checksum before trusting it.
# amd64 uses the "baseline" flavor: Proton's plain linux-x64 build requires
# AVX (x86-64-v3) since CLI 0.7/0.8 and dies with SIGILL on older CPUs and on
# VMs whose CPU model masks AVX2 (e.g. Proxmox's x86-64-v2-AES default).
RUN set -eux; \
    case "${BUILD_ARCH}" in \
        amd64) PD_ARCH="linux-x64-baseline"; PD_SHA256="${PROTON_CLI_SHA256_AMD64}" ;; \
        aarch64) PD_ARCH="linux-arm64"; PD_SHA256="${PROTON_CLI_SHA256_AARCH64}" ;; \
        *) echo "Unsupported architecture: ${BUILD_ARCH} (Proton Drive CLI ships only linux-x64/linux-arm64)"; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/bin/proton-drive \
        "https://proton.me/download/drive/cli/${PROTON_CLI_VERSION}/${PD_ARCH}/proton-drive"; \
    echo "${PD_SHA256}  /usr/bin/proton-drive" | sha256sum -c -; \
    chmod +x /usr/bin/proton-drive

COPY requirements-addon.txt /app/requirements-addon.txt
RUN pip3 install --no-cache-dir --break-system-packages -r requirements-addon.txt

COPY . /app
RUN chmod +x /app/run.sh

EXPOSE 8471
ENTRYPOINT ["/app/run.sh"]
