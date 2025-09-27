#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tashi DePIN Worker — Termux helper (EXPERIMENTAL)

Mode 1 (Android/ARM — eksperimental, sering gagal):
  python bot.py install --force

Mode 2 (disarankan, VPS x86_64):
  python bot.py vps user@IP
  python bot.py vps ubuntu@1.2.3.4:2222

Utilitas:
  python bot.py status
  python bot.py logs
  python bot.py restart
  python bot.py uninstall
  python bot.py wallet <ALAMAT_SOLANA>
  python bot.py wallet
  python bot.py rebond
  python bot.py faucet
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

UBUNTU_DISTRO = "ubuntu"
INSTALL_URL_PRIMARY = "https://depin.tashi.network/install.sh"
INSTALL_URL_ALT = "https://raw.githubusercontent.com/tashigg/tashi-depin-worker/refs/heads/main/install.sh"

CONTAINER_NAME = "tashi-depin-worker"
AUTH_VOLUME = "tashi-depin-worker-auth"

CONFIG_DIR = Path.home() / ".tashi-termux"
CONFIG_PATH = CONFIG_DIR / "config.json"

# ---------------------- Utils ----------------------
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

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            return {}
    return {}

def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))

def get_saved_wallet():
    return load_config().get("solana_wallet")

# Base58 sederhana (tanpa 0 O I l), panjang 32..48
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")
def validate_wallet(addr):
    return bool(_BASE58_RE.match(addr.strip())) if addr else False

def open_url_android(url):
    if is_cmd("am"):
        run(f'am start -a android.intent.action.VIEW -d "{url}"', check=False)
    print(f"[i] Buka di browser: {url}")

# ---------------------- Termux local/proot path ----------------------
def preflight(force=False):
    print("=== Preflight ===")
    if not is_termux():
        print("[!] Bukan di Termux. Script ini ditulis untuk Termux (Android). Lanjut tetap dicoba.")
    arch = platform.machine().lower()
    print(f"[i] Detected arch: {arch}")
    # Tashi mendukung x86_64/amd64. ARM/aarch64 akan ditolak kecuali --force.
    if "x86_64" not in arch and "amd64" not in arch:
        if not force:
            raise SystemExit(
                "\n[x] Platform ARM/aarch64 terdeteksi. Tashi saat ini mendukung x86_64/amd64 "
                "(Linux 64-bit/WSL/macOS Intel) dengan Docker/Podman.\n"
                "Jalankan di VPS/PC x86-64. Atau pakai mode paksa: python bot.py install --force\n"
                "Referensi: docs.tashi.network Node Installation."
            )
        else:
            print("[!!] FORCE MODE: Melanjutkan di ARM/aarch64. Ini eksperimental dan kemungkinan besar gagal.")
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
    ret = subprocess.run(f"proot-distro list | grep -E '^\\s*{UBUNTU_DISTRO}\\b|Installed.*{UBUNTU_DISTRO}'", shell=True)
    if ret.returncode != 0:
        run(f"proot-distro install {UBUNTU_DISTRO} || true", check=False)

def setup_inside_ubuntu():
    print("\n=== Step 3: Siapkan dependensi di Ubuntu (rootless Podman + tools) ===")
    in_proot("apt-get update -y")
    in_proot("DEBIAN_FRONTEND=noninteractive apt-get install -y "
             "bash ca-certificates curl wget iproute2 uidmap slirp4netns fuse-overlayfs podman")
    in_proot("mkdir -p $HOME/.config/containers $HOME/.local/share/containers || true", check=False)
    in_proot("podman --version || true", check=False)
    in_proot("podman info >/dev/null 2>&1 || true", check=False)

def run_tashi_install():
    print("\n=== Step 4: Jalankan installer resmi Tashi (mode interaktif) ===")
    # Coba primary, jika gagal pakai alternatif
    cmd = (
        "set -e; "
        "if command -v curl >/dev/null 2>&1; then "
        f"bash -lc 'curl -fsSL {INSTALL_URL_PRIMARY} | bash -s -' || "
        f"bash -lc 'curl -fsSL {INSTALL_URL_ALT} | bash -s -'; "
        "else "
        f"bash -lc 'wget -qO- {INSTALL_URL_PRIMARY} | bash -s -' || "
        f"bash -lc 'wget -qO- {INSTALL_URL_ALT} | bash -s -'; "
        "fi"
    )
    in_proot(cmd, check=True)

def show_next_steps():
    print(dedent("""
    === Langkah Lanjut ===
    • Installer akan menampilkan URL "bond worker". Buka di browser (Phantom/Solflare Devnet),
      connect wallet, sign, klik "Copy License", lalu paste token ke terminal — ini yang menetapkan
      operator address (penerima reward).
    • Butuh SOL Devnet? Faucet: https://faucet.solana.com/
    • Untuk earning optimal, buka UDP 39065 dari publik (kalau NAT/seluler tertutup, earning bisa berkurang).
    """).strip())
    wal = get_saved_wallet()
    if wal:
        print(f"    • Wallet Solana (devnet) yang kamu set: {wal}")

# ---------------------- VPS Provisioning via SSH (disarankan) ----------------------
def cmd_vps(target):
    """
    Provision & run Tashi installer di VPS x86_64 via SSH.
    Argumen: target -> 'user@host' atau 'user@host:port'
    """
    if ":" in target:
        host, port = target.split(":", 1)
    else:
        host, port = target, "22"

    if not is_cmd("ssh"):
        raise SystemExit("[x] 'ssh' tidak ditemukan. Pasang openssh: pkg install openssh")

    print("=== Provisioning ke VPS ===")
    # Validasi arsitektur & siapkan runtime di remote, lalu jalankan installer resmi
    remote = (
        "set -e; "
        'ARCH=$(uname -m); if [ \"$ARCH\" != \"x86_64\" ] && [ \"$ARCH\" != \"amd64\" ]; then '
        'echo \"[x] Unsupported arch on VPS: $ARCH (butuh x86_64/amd64)\"; exit 2; fi; '
        "if ! command -v curl >/dev/null 2>&1; then sudo apt-get update -y && sudo apt-get install -y curl ca-certificates; fi; "
        "if ! command -v docker >/dev/null 2>&1 && ! command -v podman >/dev/null 2>&1; then "
        "  curl -fsSL https://get.docker.com | sh; "
        "fi; "
        "(command -v ufw >/dev/null 2>&1 && sudo ufw allow 39065/udp) || true; "
        f"curl -fsSL {INSTALL_URL_PRIMARY} | sudo bash -s - || curl -fsSL {INSTALL_URL_ALT} | sudo bash -s -"
    )
    run(f"ssh -p {port} {host} '{remote}'", check=True)

    print(dedent("""
    [✓] Installer Tashi dijalankan di VPS.
    • Perhatikan output SSH tadi: akan ada URL "bond worker". Buka dengan wallet Solana (Devnet),
      sign, lalu paste License Token ke terminal VPS saat diminta.
    • Cek status/logs di VPS dengan perintah docker/podman standar.
    """))

# ---------------------- Commands ----------------------
def cmd_status():
    print("=== Status Worker (jika local proot digunakan) ===")
    cmd1 = ("podman ps -a --format 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}' | "
            "(grep -E '(" + CONTAINER_NAME + "|NAMES)' || true)")
    in_proot(cmd1, check=False)

    print("\n=== Detail (jika tersedia) ===")
    cmd2 = ("podman inspect " + CONTAINER_NAME + " >/dev/null 2>&1 && "
            "podman inspect " + CONTAINER_NAME + " --format '{{.State.Status}} {{.Config.Image}}' || true")
    in_proot(cmd2, check=False)

    saved = get_saved_wallet()
    if saved:
        print(f"\n[i] Wallet tersimpan (panduan saat bonding): {saved}")

def cmd_logs():
    print("=== Logs (CTRL+C untuk keluar) ===")
    in_proot("podman logs -f " + CONTAINER_NAME)

def cmd_restart():
    print("=== Restart Worker ===")
    in_proot("podman restart " + CONTAINER_NAME)

def cmd_uninstall():
    print("=== Uninstall Worker ===")
    in_proot("podman rm -f " + CONTAINER_NAME + " || true")
    in_proot("podman rm -f " + CONTAINER_NAME + "-old || true")
    in_proot("podman volume rm " + AUTH_VOLUME + " || true")
    print("[i] Selesai uninstall. Jalankan 'python bot.py' untuk memasang ulang.")

def cmd_wallet(addr):
    cfg = load_config()
    if addr:
        if not validate_wallet(addr):
            raise SystemExit("[x] Alamat wallet tidak valid. Gunakan alamat Solana base58.")
        cfg["solana_wallet"] = addr.strip()
        save_config(cfg)
        print(f"[✓] Wallet Solana disimpan: {addr.strip()}")
        print("[i] Saat bonding, pilih wallet ini di Phantom/Solflare (Devnet).")
    else:
        cur = cfg.get("solana_wallet")
        if cur:
            print(f"[i] Wallet tersimpan: {cur}")
        else:
            print("[i] Belum ada wallet. Set dengan: python bot.py wallet <ALAMAT_SOLANA>")

def cmd_rebond():
    print("=== Rebond (reset otorisasi & ulangi pemasangan) ===")
    in_proot("podman rm -f " + CONTAINER_NAME + " || true")
    in_proot("podman volume rm " + AUTH_VOLUME + " || true")
    run_tashi_install()
    show_next_steps()

def cmd_faucet():
    print("=== Buka Faucet Devnet ===")
    open_url_android("https://faucet.solana.com/")
    wal = get_saved_wallet()
    if wal:
        print(f"[i] Tempel alamat ini di faucet: {wal}")

# ---------------------- Entry ----------------------
def main():
    ap = argparse.ArgumentParser(description="Tashi DePIN Worker helper for Termux (experimental)")
    ap.add_argument(
        "action",
        nargs="?",
        choices=["install", "vps", "status", "logs", "restart", "uninstall", "wallet", "rebond", "faucet"],
        default="install",
        help="Aksi (default: install)"
    )
    ap.add_argument("value", nargs="?", help="Tambahan (mis. user@host untuk 'vps', atau alamat untuk 'wallet')")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Bypass cek arsitektur (Android/ARM). TIDAK didukung resmi."
    )
    args = ap.parse_args()

    if len(sys.argv) == 1:
        print("[i] Tidak ada argumen. Menjalankan default: install\n")

    if args.action == "install":
        preflight(force=args.force)
        install_termux_prereqs()
        ensure_ubuntu_proot()
        setup_inside_ubuntu()
        wal = get_saved_wallet()
        if wal:
            print(f"[i] Gunakan wallet ini saat bonding: {wal}")
        run_tashi_install()
        show_next_steps()
    elif args.action == "vps":
        if not args.value:
            raise SystemExit("Usage: python bot.py vps user@host[:port]")
        cmd_vps(args.value)
    elif args.action == "status":
        cmd_status()
    elif args.action == "logs":
        cmd_logs()
    elif args.action == "restart":
        cmd_restart()
    elif args.action == "uninstall":
        cmd_uninstall()
    elif args.action == "wallet":
        cmd_wallet(args.value)
    elif args.action == "rebond":
        cmd_rebond()
    elif args.action == "faucet":
        cmd_faucet()

if __name__ == "__main__":
    main()
