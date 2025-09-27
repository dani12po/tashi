#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tashi DePIN Worker — Termux helper (EXPERIMENTAL)
- Termux -> proot-distro (Ubuntu) -> Podman (rootless) -> Tashi install.sh
- Jalankan cukup:  python bot.py
  (default ke 'install' bila tanpa argumen)
- Sub-commands (opsional):
    python bot.py install
    python bot.py status
    python bot.py logs
    python bot.py restart
    python bot.py uninstall
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from textwrap import dedent

UBUNTU_DISTRO = "ubuntu"
INSTALL_URL_PRIMARY = "https://depin.tashi.network/install.sh"
INSTALL_URL_ALT = "https://raw.githubusercontent.com/tashigg/tashi-depin-worker/refs/heads/main/install.sh"

CONTAINER_NAME = "tashi-depin-worker"
AUTH_VOLUME = "tashi-depin-worker-auth"

def run(cmd, check=True, shell=True, env=None):
    print(f"\n>> {cmd}")
    proc = subprocess.run(cmd, shell=shell, env=env)
    if check and proc.returncode != 0:
        raise SystemExit(f"[!] Command gagal (exit={proc.returncode}): {cmd}")
    return proc.returncode

def in_proot(cmd, check=True):
    full = f'proot-distro login {UBUNTU_DISTRO} -- bash -lc "{cmd}"'
    return run(full, check=check, shell=True)

def is_cmd(name):
    return shutil.which(name) is not None

def is_termux():
    return os.path.exists("/data/data/com.termux/files/usr")

def preflight():
    print("=== Preflight ===")
    if not is_termux():
        print("[!] Bukan di Termux. Script ini ditulis untuk Termux (Android). Lanjut tetap dicoba.")
    arch = platform.machine().lower()
    print(f"[i] Detected arch: {arch}")
    if "x86_64" not in arch and "amd64" not in arch:
        print("[!] Peringatan: arsitektur non-x86_64 (mis. arm64/Android). "
              "Tashi resmi butuh Docker/Podman di OS 64-bit yang didukung; Termux tidak resmi (eksperimental).")
    if not is_cmd("pkg"):
        raise SystemExit("[x] Perintah 'pkg' tidak ditemukan. Pastikan memakai Termux.")

def install_termux_prereqs():
    print("\n=== Step 1: Install paket Termux (proot-distro, curl, dll) ===")
    run("yes | pkg update -y || true", check=False)
    run("yes | pkg upgrade -y || true", check=False)
    run("yes | pkg install -y proot-distro curl wget tar ca-certificates git openssh", check=True)

def ensure_ubuntu_proot():
    print("\n=== Step 2: Install Ubuntu (proot-distro) ===")
    run("proot-distro list", check=False)
    # cek apakah ubuntu sudah ada
    ret = subprocess.run(f"proot-distro list | grep -E '^\\s*{UBUNTU_DISTRO}\\b|Installed.*{UBUNTU_DISTRO}'", shell=True)
    if ret.returncode != 0:
        run(f"proot-distro install {UBUNTU_DISTRO} || true", check=False)

def setup_inside_ubuntu():
    print("\n=== Step 3: Siapkan dependensi di Ubuntu (rootless Podman + tools) ===")
    in_proot("apt-get update -y")
    in_proot("DEBIAN_FRONTEND=noninteractive apt-get install -y "
             "bash ca-certificates curl wget iproute2 uidmap slirp4netns fuse-overlayfs podman")
    # Rootless env minimal (kadang perlu di proot)
    in_proot("mkdir -p $HOME/.config/containers && mkdir -p $HOME/.local/share/containers || true", check=False)
    # Sanity checks (jika gagal, jangan hentikan seluruh flow)
    in_proot("podman --version || true", check=False)
    in_proot("podman info >/dev/null 2>&1 || true", check=False)

def run_tashi_install():
    print("\n=== Step 4: Jalankan installer resmi Tashi (mode interaktif) ===")
    # coba primary, kalau gagal pakai alternatif
    cmd = dedent(f"""
        set -e
        if command -v curl >/dev/null 2>&1; then
            bash -lc 'curl -fsSL {INSTALL_URL_PRIMARY} | bash -s -' \
            || bash -lc 'curl -fsSL {INSTALL_URL_ALT} | bash -s -'
        else
            bash -lc 'wget -qO- {INSTALL_URL_PRIMARY} | bash -s -' \
            || bash -lc 'wget -qO- {INSTALL_URL_ALT} | bash -s -'
        fi
    """).strip().replace("\n", " ")
    in_proot(cmd, check=True)

def show_next_steps():
    print(dedent(f"""
    === Langkah Lanjut ===
    • Installer akan menampilkan URL "bond worker" + meminta Authorization Token.
      Buka URL itu di browser (wallet Solana devnet aktif), selesaikan bonding, lalu paste token ke terminal.
    • Port UDP 39065 idealnya terbuka dari internet. Di jaringan seluler/NAT bisa tertutup (earning bisa berkurang).

    Perintah cepat:
      python {os.path.basename(__file__)} status     # lihat container & versi
      python {os.path.basename(__file__)} logs       # follow log worker
      python {os.path.basename(__file__)} restart    # restart worker
      python {os.path.basename(__file__)} uninstall  # hapus container + auth volume (reset bonding)

    Catatan: Podman di Termux/proot itu eksperimen; kalau mentok, gunakan VPS/PC Linux x86-64 untuk hasil stabil.
    """))

def cmd_status():
    print("=== Status Worker ===")
    in_proot(f"podman ps -a --format 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}' | (grep -E '({CONTAINER_NAME}|NAMES)' || true)")
    in_proot(f"podman inspect {CONTAINER_NAME} >/dev/null 2>&1 && podman inspect {CONTAINER_NAME} --format '{{{{.State.Status}}}} {{{{.Config.Image}}}}' || true")

def cmd_logs():
    print("=== Logs (CTRL+C untuk keluar) ===")
    in_proot(f"podman logs -f {CONTAINER_NAME}")

def cmd_restart():
    print("=== Restart Worker ===")
    in_proot(f"podman restart {CONTAINER_NAME}")

def cmd_uninstall():
    print("=== Uninstall Worker ===")
    in_proot(f"podman rm -f {CONTAINER_NAME} || true")
    in_proot(f"podman rm -f {CONTAINER_NAME}-old || true")
    in_proot(f"podman volume rm {AUTH_VOLUME} || true")
    print("[i] Selesai uninstall. Jalankan 'python bot.py' untuk memasang ulang.")

def main():
    # Default ke 'install' bila tanpa argumen
    ap = argparse.ArgumentParser(description="Tashi DePIN Worker helper for Termux (experimental)")
    ap.add_argument(
        "action",
        nargs="?",
        choices=["install", "status", "logs", "restart", "uninstall"],
        default="install",
        help="Aksi (default: install)"
    )
    args = ap.parse_args()

    # Tampilkan info kalau user memang tidak memberi argumen
    if len(sys.argv) == 1:
        print("[i] Tidak ada argumen diberikan. Menjalankan default: install\n")

    if args.action == "install":
        preflight()
        install_termux_prereqs()
        ensure_ubuntu_proot()
        setup_inside_ubuntu()
        run_tashi_install()
        show_next_steps()
    elif args.action == "status":
        cmd_status()
    elif args.action == "logs":
        cmd_logs()
    elif args.action == "restart":
        cmd_restart()
    elif args.action == "uninstall":
        cmd_uninstall()

if __name__ == "__main__":
    main()
