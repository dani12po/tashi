#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tashi DePIN Worker — Termux helper (EXPERIMENTAL)
- Termux -> proot-distro (Ubuntu) -> Podman (rootless) -> Tashi install.sh
- Jalankan cukup:  python bot.py   (default: install)
- Sub-commands:
    python bot.py install        # pasang & jalankan installer interaktif
    python bot.py status         # status kontainer + operator address
    python bot.py logs           # follow log worker
    python bot.py restart        # restart worker
    python bot.py uninstall      # hapus worker + auth volume
    python bot.py wallet <ADDR>  # simpan/ganti wallet Solana (devnet)
    python bot.py wallet         # lihat wallet tersimpan
    python bot.py rebond         # reset otorisasi & ulangi pemasangan (untuk ganti wallet)
    python bot.py faucet         # buka faucet devnet di browser Android
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from textwrap import dedent
from pathlib import Path

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

def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))

def get_saved_wallet() -> str | None:
    return load_config().get("solana_wallet")

# Very lightweight Solana address check: base58 (no 0 O I l), length ~32..48 chars
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")

def validate_wallet(addr: str) -> bool:
    return bool(_BASE58_RE.match(addr.strip()))

def open_url_android(url: str):
    # Buka URL di browser Android bila 'am' tersedia, selain itu hanya cetak URL-nya
    if is_cmd("am"):
        run(f'am start -a android.intent.action.VIEW -d "{url}"', check=False)
    print(f"[i] Buka di browser: {url}")

# ---------------------- Steps ----------------------
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
    # Sesuai docs: installer akan menampilkan URL 'bond-worker' unik dan meminta License Token (operator wallet devnet menandatangani lalu copy token) :contentReference[oaicite:2]{index=2}
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
    wal = get_saved_wallet()
    wallet_hint = f"\n    • Wallet Solana (devnet) yang kamu set: {wal}" if wal else ""
    print(dedent(f"""
    === Langkah Lanjut ===
    • Saat installer menampilkan URL "bond worker", buka URL itu di browser Android (Phantom/solflare devnet),
      connect wallet, sign, lalu klik "Copy License" dan paste token ke terminal. (Inilah yang menetapkan operator address & penerima reward). :contentReference[oaicite:3]{index=3}{wallet_hint}
    • Kalau wallet belum berisi devnet SOL, isi dulu via faucet resmi: faucet.solana.com (Devnet). :contentReference[oaicite:4]{index=4}
    • Port UDP 39065 sebaiknya terbuka publik agar earning optimal (bila NAT/seluler, earning bisa berkurang). :contentReference[oaicite:5]{index=5}
    """))

# ---------------------- Commands ----------------------
def cmd_status():
    print("=== Status Worker ===")
    in_proot(f"podman ps -a --format 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}' | (grep -E '({CONTAINER_NAME}|NAMES)' || true)")
    # Coba tampilkan Operator address dari log terakhir saat authorize
    print("\n=== Operator Address (dari log, jika ada) ===")
    in_proot(f"podman logs {CONTAINER_NAME} 2>/dev/null | grep -m1 -E 'Operator address:' || true")
    saved = get_saved_wallet()
    if saved:
        print(f"\n[i] Wallet tersimpan (untuk panduan bonding): {saved}")

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

def cmd_wallet(addr: str | None):
    cfg = load_config()
    if addr:
        if not validate_wallet(addr):
            raise SystemExit("[x] Alamat wallet tidak valid. Gunakan alamat Solana base58 (devnet/mainnet sama formatnya).")
        cfg["solana_wallet"] = addr
        save_config(cfg)
        print(f"[✓] Wallet Solana disimpan: {addr}")
        print("[i] Saat bonding, pilih wallet ini di Phantom/solflare (mode Devnet).")
    else:
        cur = cfg.get("solana_wallet")
        if cur:
            print(f"[i] Wallet tersimpan: {cur}")
        else:
            print("[i] Belum ada wallet tersimpan. Set dengan: python bot.py wallet <ALAMAT_SOLANA>")

def cmd_rebond():
    print("=== Rebond (reset otorisasi & ulangi pemasangan) ===")
    # Hapus auth volume agar token lama terhapus, lalu jalankan installer lagi
    in_proot(f"podman rm -f {CONTAINER_NAME} || true")
    in_proot(f"podman volume rm {AUTH_VOLUME} || true")
    run_tashi_install()
    show_next_steps()

def cmd_faucet():
    wal = get_saved_wallet()
    print("=== Buka Faucet Devnet ===")
    open_url_android("https://faucet.solana.com/")
    if wal:
        print(f"[i] Tempel alamat ini di kolom faucet: {wal}")

# ---------------------- Entry ----------------------
def main():
    ap = argparse.ArgumentParser(description="Tashi DePIN Worker helper for Termux (experimental)")
    ap.add_argument(
        "action",
        nargs="?",
        choices=["install", "status", "logs", "restart", "uninstall", "wallet", "rebond", "faucet"],
        default="install",
        help="Aksi (default: install)"
    )
    ap.add_argument("value", nargs="?", help="Nilai tambahan (mis. untuk 'wallet <ALAMAT>')")
    args = ap.parse_args()

    if len(sys.argv) == 1:
        print("[i] Tidak ada argumen. Menjalankan default: install\n")

    if args.action == "install":
        preflight()
        install_termux_prereqs()
        ensure_ubuntu_proot()
        setup_inside_ubuntu()
        # Info wallet sebelum masuk installer
        wal = get_saved_wallet()
        if wal:
            print(f"[i] Gunakan wallet ini saat proses bonding: {wal}")
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
    elif args.action == "wallet":
        cmd_wallet(args.value)
    elif args.action == "rebond":
        cmd_rebond()
    elif args.action == "faucet":
        cmd_faucet()

if __name__ == "__main__":
    main()
