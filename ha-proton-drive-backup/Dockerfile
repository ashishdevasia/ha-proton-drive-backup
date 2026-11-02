ARG BUILD_FROM
FROM $BUILD_FROM

# Provided by the Home Assistant build system (amd64 / aarch64).
ARG BUILD_ARCH
ARG PROTON_CLI_VERSION=0.9.0
# SHA256 of the official CLI binaries for PROTON_CLI_VERSION (per architecture;
# note the amd64 build must run without AVX, see the download step below).
# Proton publishes SHA-512 checksums at https://proton.me/download/drive/cli/index.html;
# these are the SHA256 of the same binaries, pinned here and must be refreshed
# whenever PROTON_CLI_VERSION changes.
ARG PROTON_CLI_SHA256_AMD64=4f66f984b6361084d46567b8f4fd4851f4271eb9f77e5d181e1eff3c8a332501
ARG PROTON_CLI_SHA256_AARCH64=63033ed3bc7d262d074bfd0ec123303112bb9f85d2414c24e8c9f07e6ab27d30
# Debian bookworm ships pip 23.0.1; the add-on's dependencies are installed with
# this release instead (SHA256 of its py3-none-any wheel on PyPI).
ARG PIP_VERSION=26.2.2
ARG PIP_SHA256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70

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
# amd64 must run without AVX: CLI 0.7/0.8's plain linux-x64 build required AVX
# (x86-64-v3) and died with SIGILL on older CPUs and on VMs whose CPU model
# masks AVX2 (e.g. Proxmox's x86-64-v2-AES default), so those versions used the
# separate "linux-x64-baseline" flavor.  0.9.0 ships only plain linux-x64: it's
# built with Bun 1.4, whose sole x64 target is Nehalem (no AVX), and it ran
# under an emulated pre-AVX CPU.  Re-check on every bump.
# The CLI trusts only the CA roots compiled into it and never checks
# revocation, so distrust_roots.py neutralises roots that have since been
# distrusted (it's a no-op once Proton ships a CLI without them), then runs
# the CLI to confirm none of them is still in its live trust store.
COPY distrust_roots.py /tmp/distrust_roots.py
RUN set -eux; \
    case "${BUILD_ARCH}" in \
        amd64) PD_ARCH="linux-x64"; PD_SHA256="${PROTON_CLI_SHA256_AMD64}" ;; \
        aarch64) PD_ARCH="linux-arm64"; PD_SHA256="${PROTON_CLI_SHA256_AARCH64}" ;; \
        *) echo "Unsupported architecture: ${BUILD_ARCH} (Proton Drive CLI ships only linux-x64/linux-arm64)"; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/bin/proton-drive \
        "https://proton.me/download/drive/cli/${PROTON_CLI_VERSION}/${PD_ARCH}/proton-drive"; \
    echo "${PD_SHA256}  /usr/bin/proton-drive" | sha256sum -c -; \
    chmod +x /usr/bin/proton-drive; \
    python3 /tmp/distrust_roots.py /usr/bin/proton-drive; \
    python3 /tmp/distrust_roots.py --verify /usr/bin/proton-drive; \
    rm /tmp/distrust_roots.py

# Upgrade pip (into /usr/local, which shadows Debian's copy), then install the
# fully pinned, hash-checked dependency lock as wheels only.  Regenerate the
# lock after editing requirements-addon.txt (command in the lock's header).
RUN set -eux; \
    echo "pip==${PIP_VERSION} --hash=sha256:${PIP_SHA256}" > /tmp/pip.txt; \
    pip3 install --no-cache-dir --break-system-packages --require-hashes --only-binary :all: -r /tmp/pip.txt; \
    rm /tmp/pip.txt; \
    python3 -m pip --version | grep -F "pip ${PIP_VERSION} "
COPY requirements-addon.lock /app/requirements-addon.lock
RUN python3 -m pip install --no-cache-dir --break-system-packages --require-hashes --only-binary :all: \
        -r requirements-addon.lock

COPY . /app
RUN chmod +x /app/run.sh

EXPOSE 8471
ENTRYPOINT ["/app/run.sh"]
