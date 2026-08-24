ARG BUILD_FROM
FROM $BUILD_FROM

# Provided by the Home Assistant build system (amd64 / aarch64).
ARG BUILD_ARCH
ARG PROTON_CLI_VERSION=0.8.0
# SHA256 of the official CLI binaries for PROTON_CLI_VERSION (per architecture).
# Proton publishes SHA-512 checksums at https://proton.me/download/drive/cli/index.html;
# these are the SHA256 of the same binaries, pinned here and must be refreshed
# whenever PROTON_CLI_VERSION changes.
ARG PROTON_CLI_SHA256_AMD64=9443d771719c892790db17e6f02ecd99ad7c53593329f3a67c77677dce577735
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
RUN set -eux; \
    case "${BUILD_ARCH}" in \
        amd64) PD_ARCH="linux-x64"; PD_SHA256="${PROTON_CLI_SHA256_AMD64}" ;; \
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
