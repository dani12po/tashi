#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tashi DePIN Worker — Termux/VPS helper (PUBLIC VPS AUTOMATION)

📦 Mode VPS (disarankan):
  # Set sekali, simpan target VPS publik (x86_64)
  python bot.py vps-set ubuntu@203.0.113.45
  # Jika SSH port custom:
  python bot.py vps-set ubuntu@203.0.113.45:2222

  # Jalankan provisioning + installer resmi Tashi di VPS
  python bot.py vps-run

  # Utilitas jarak jauh:
  python bot.py vps-status
  python bot.py vps-logs
  python bot.py vps-open-port
  python bot.py vps-rebond
  python bot.py vps-uninstall

💡 Opsi cepat tanpa menyimpan:
  python bot.py vps ubuntu@203.0.113.45[:port]

💳 Wallet & faucet:
  python bot.py wallet <ALAMAT_SOLANA>
  python bot.py wallet
  python bot.py faucet

🛠️ Mode Termux lokal (ARM) — eksperimental:
  python bot.py install --force
  python bot.py status|logs|restart|uninstall
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

# -------------------- Konstanta --------------------
UBUNTU_DISTRO = "ubuntu"
INSTALL_URL_PRIMARY = "https://depin.tashi.network/install.sh"
INSTALL_URL_ALT = "https://raw.githubusercontent.com/tashigg/tashi-depin-worker/refs/heads/main/install.sh"

CONTAINER_NAME = "tashi-depin-worker"
AUTH_VOLUME = "tashi-depin-worker-auth"

CONFIG_DIR = Path.home() / ".tashi-termux"
CONFIG_PATH = CONFIG_DIR / "config.json"

# -------------------- Util umum --------------------
def run(cmd, check=True, shell=True, env=None):
    print(f"\n>> {cmd}")
    proc = subprocess.run(cmd, shell=shell, env=env)
    if check and proc.returncode != 0:
        raise SystemExit(f"[!] Command gagal (exit={proc.returncode}): {cmd}")
    return proc.returncode

def is_cmd(name): return shutil.which(name) is not None
def is_termux(): return os.path.exists("/data/data/com.termux/files/usr")

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

def get_saved_vps():
    return load_config().get("vps_target")

def set_saved_vps(target: str):
    cfg = load_config()
    cfg["vps_target"] = target.strip()
    save_config(cfg)

# Base58 sederhana (tanpa 0 O I l), panjang 32..48
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")
def validate_wallet(addr):
    return bool(_BASE58_RE.match(addr.strip())) if addr else False

def open_url_android(url):
    if is_cmd("am"):
        run(f'am start -a android.intent.action.VIEW -d "{url}"', check=False)
    print(f"[i] Buka di browser: {url}")

# -------------------- SSH helper (VPS) --------------------
def parse_target(target: str | None):
    """Return (userhost, port) dari string 'user@host[:port]' atau dari config."""
    if target is None:
        target = get_saved_vps()
        if not target:
            raise SystemExit("[x] Belum ada VPS tersimpan. Jalankan: python bot.py vps-set user@IP[:port]")
    if ":" in target:
        userhost, port = target.rsplit(":", 1)
    else:
        userhost, port = target, "22"
    return userhost, port

def ssh_run(target: str | None, remote_cmd: str, trust=False, check=True):
    userhost, port = parse_target(target)
    opts = f"-p {port}"
    if trust:
        opts += " -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
    return run(f"ssh {opts} {userhost} '{remote_cmd}'", check=check)

def ssh_runtime_selector():
    """Snippet bash untuk memilih docker/podman di sisi VPS."""
    return (
        'if command -v docker >/dev/null 2>&1; then R=docker; '
        'elif command -v podman >/dev/null 2>&1; then R=podman; '
        'else R=""; fi;'
    )

# -------------------- Jalur Termux lokal (proot) --------------------
def in_proot(cmd, check=True):
    full = f'proot-distro login {UBUNTU_DISTRO} -- bash -lc "{cmd}"'
    return run(full, check=check, shell=True)

def preflight(force=False):
    print("=== Preflight ===")
    if not is_termux():
        print("[!] Bukan di Termux. Script ini untuk Termux (Android). Lanjut tetap dicoba.")
    arch = platform.machine().lower()
    print(f"[i] Detected arch: {arch}")
    if "x86_64" not in arch and "amd64" not in arch:
        if not force:
            raise SystemExit(
                "\n[x] Platform ARM/aarch64 terdeteksi. Tashi saat ini mendukung x86_64/amd64 "
                "(Linux 64-bit/WSL/macOS Intel) dengan Docker/Podman.\n"
                "Gunakan VPS publik: python bot.py vps-set user@IP  lalu  python bot.py vps-run\n"
                "Atau pakai paksa (eksperimental): python bot.py install --force"
            )
        else:
            print("[!!] FORCE MODE: Melanjutkan di ARM/aarch64. Kemungkinan besar gagal (platform check/runtime).")
    if not is_cmd("pkg"):
        raise SystemExit("[x] Perintah 'pkg' tidak ditemukan. Pastikan memakai Termux.")

def install_termux_prereqs():
    print("\n=== Step 1: Install paket Termux ===")
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
    print("\n=== Step 3: Dependensi di Ubuntu (rootless Podman + tools) ===")
    in_proot("apt-get update -y")
    in_proot("DEBIAN_FRONTEND=noninteractive apt-get install -y "
             "bash ca-certificates curl wget iproute2 uidmap slirp4netns fuse-overlayfs podman")
    in_proot("mkdir -p $HOME/.config/containers $HOME/.local/share/containers || true", check=False)
    in_proot("podman --version || true", check=False)
    in_proot("podman info >/dev/null 2>&1 || true", check=False)

def run_tashi_install_local():
    print("\n=== Step 4 (LOCAL): Installer Tashi (interaktif) ===")
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
    • Faucet SOL Devnet: https://faucet.solana.com/
    • Buka UDP 39065 di firewall VPS agar earning optimal.
    """).strip())
    wal = get_saved_wallet()
    if wal:
        print(f"    • Wallet Solana (devnet) yang kamu set: {wal}")

# -------------------- Jalur VPS publik (otomatis) --------------------
def remote_assert_x86_64():
    return (
        'ARCH=$(uname -m); '
        'if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "amd64" ]; then '
        'echo "[x] Unsupported arch on VPS: $ARCH (butuh x86_64/amd64)"; exit 2; fi;'
    )

def remote_prepare_runtime():
    # Pasang curl, lalu pilih docker/podman (install docker jika keduanya tak ada)
    return (
        "if ! command -v curl >/dev/null 2>&1; then "
        "  sudo apt-get update -y && sudo apt-get install -y curl ca-certificates; "
        "fi; "
        "if ! command -v docker >/dev/null 2>&1 && ! command -v podman >/dev/null 2>&1; then "
        "  curl -fsSL https://get.docker.com | sh; "
        "fi; "
    )

def remote_open_port():
    # UFW kalau ada; jika tidak ada, biarkan user atur manual
    return "(command -v ufw >/dev/null 2>&1 && sudo ufw allow 39065/udp) || true;"

def remote_install_tashi():
    return (
        f"curl -fsSL {INSTALL_URL_PRIMARY} | sudo bash -s - || "
        f"curl -fsSL {INSTALL_URL_ALT} | sudo bash -s -"
    )

def vps_run_once(target: str | None, trust=False):
    """Provision + jalankan installer Tashi resmi di VPS publik."""
    remote = (
        "set -e; "
        + remote_assert_x86_64()
        + remote_prepare_runtime()
        + remote_open_port()
        + remote_install_tashi()
    )
    ssh_run(target, remote, trust=trust, check=True)
    print(dedent("""
    [✓] Installer Tashi telah dijalankan di VPS.
    • Perhatikan output SSH (di atas): ada URL "bond worker".
      Buka di HP (Phantom/Solflare Devnet), sign, lalu paste License Token ke terminal VPS saat diminta.
    """))

def vps_status(target: str | None, trust=False):
    ssh_run(target, ssh_runtime_selector() + " if [ -n \"$R\" ]; then $R ps -a; else echo 'docker/podman tidak ditemukan'; fi", trust=trust, check=False)

def vps_logs(target: str | None, trust=False):
    ssh_run(target, ssh_runtime_selector() + f" if [ -n \"$R\" ]; then $R logs -f {CONTAINER_NAME}; else echo 'docker/podman tidak ditemukan'; fi", trust=trust, check=False)

def vps_open_port(target: str | None, trust=False):
    ssh_run(target, remote_open_port(), trust=trust, check=False)
    print("[i] Port UDP 39065 sudah di-allow (UFW). Jika tidak pakai UFW, atur firewall provider/iptables manual.")

def vps_uninstall(target: str | None, trust=False):
    remote = (
        "set -e; " + ssh_runtime_selector() +
        f" if [ -n \"$R\" ]; then $R rm -f {CONTAINER_NAME} || true; " +
        f"$R rm -f {CONTAINER_NAME}-old || true; $R volume rm {AUTH_VOLUME} || true; " +
        "echo '[i] Worker & auth volume dihapus.'; else echo 'docker/podman tidak ditemukan'; fi"
    )
    ssh_run(target, remote, trust=trust, check=False)

def vps_rebond(target: str | None, trust=False):
    remote = (
        "set -e; " + ssh_runtime_selector() +
        f" if [ -n \"$R\" ]; then $R rm -f {CONTAINER_NAME} || true; $R volume rm {AUTH_VOLUME} || true; " +
        remote_install_tashi() +
        "; else echo 'docker/podman tidak ditemukan'; fi"
    )
    ssh_run(target, remote, trust=trust, check=True)
    print("[i] Rebond dijalankan. Buka lagi URL bond worker dari output SSH.")

# -------------------- Commands lokal (proot) --------------------
def cmd_status_local():
    print("=== Status Worker (LOCAL proot) ===")
    in_proot("podman ps -a --format 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}' | (grep -E '(tashi|NAMES)' || true)", check=False)
    print("\n=== Detail (jika tersedia) ===")
    in_proot("podman inspect tashi-depin-worker >/dev/null 2>&1 && podman inspect tashi-depin-worker --format '{{.State.Status}} {{.Config.Image}}' || true", check=False)
    saved = get_saved_wallet()
    if saved: print(f"\n[i] Wallet tersimpan (panduan saat bonding): {saved}")

def cmd_logs_local():
    print("=== Logs (LOCAL, CTRL+C untuk keluar) ===")
    in_proot("podman logs -f tashi-depin-worker", check=False)

def cmd_restart_local():
    print("=== Restart Worker (LOCAL) ===")
    in_proot("podman restart tashi-depin-worker", check=False)

def cmd_uninstall_local():
    print("=== Uninstall Worker (LOCAL) ===")
    in_proot("podman rm -f tashi-depin-worker || true", check=False)
    in_proot("podman rm -f tashi-depin-worker-old || true", check=False)
    in_proot(f"podman volume rm {AUTH_VOLUME} || true", check=False)
    print("[i] Selesai uninstall lokal.")

# -------------------- Entry --------------------
def main():
    ap = argparse.ArgumentParser(description="Tashi DePIN Worker helper (Termux/VPS)")
    ap.add_argument(
        "action",
        nargs="?",
        choices=[
            # VPS public operations
            "vps", "vps-set", "vps-run", "vps-status", "vps-logs", "vps-open-port", "vps-uninstall", "vps-rebond",
            # Local proot operations
            "install", "status", "logs", "restart", "uninstall",
            # Wallet & faucet
            "wallet", "faucet"
        ],
        default="install",
        help="Aksi (default: install)"
    )
    ap.add_argument("value", nargs="?", help="Tambahan (user@IP[:port] untuk VPS, atau alamat untuk wallet)")
    ap.add_argument("--force", action="store_true", help="Bypass cek arsitektur (Android/ARM). Tidak didukung resmi.")
    ap.add_argument("--trust-host", action="store_true", help="Auto-accept host key (SSH). Tidak disarankan, tapi praktis.")
    args = ap.parse_args()

    if len(sys.argv) == 1:
        print("[i] Tidak ada argumen. Menjalankan default: install\n")

    # ===== VPS path =====
    if args.action in {"vps", "vps-run"}:
        # vps [user@host[:port]]  atau gunakan yang tersimpan
        target = args.value  # boleh None → pakai tersimpan
        vps_run_once(target, trust=args.trust_host)
        return
    elif args.action == "vps-set":
        if not args.value:
            raise SystemExit("Usage: python bot.py vps-set user@IP[:port]")
        set_saved_vps(args.value)
        print(f"[✓] VPS tersimpan: {args.value}")
        return
    elif args.action == "vps-status":
        vps_status(args.value, trust=args.trust_host)
        return
    elif args.action == "vps-logs":
        vps_logs(args.value, trust=args.trust_host)
        return
    elif args.action == "vps-open-port":
        vps_open_port(args.value, trust=args.trust_host)
        return
    elif args.action == "vps-uninstall":
        vps_uninstall(args.value, trust=args.trust_host)
        return
    elif args.action == "vps-rebond":
        vps_rebond(args.value, trust=args.trust_host)
        return

    # ===== Local Termux/proot path =====
    if args.action == "install":
        preflight(force=args.force)
        install_termux_prereqs()
        ensure_ubuntu_proot()
        setup_inside_ubuntu()
        wal = get_saved_wallet()
        if wal:
            print(f"[i] Gunakan wallet ini saat bonding: {wal}")
        run_tashi_install_local()
        show_next_steps()
        return
    elif args.action == "status":
        cmd_status_local(); return
    elif args.action == "logs":
        cmd_logs_local(); return
    elif args.action == "restart":
        cmd_restart_local(); return
    elif args.action == "uninstall":
        cmd_uninstall_local(); return

    # ===== Wallet & faucet =====
    if args.action == "wallet":
        if args.value:
            addr = args.value.strip()
            if not validate_wallet(addr):
                raise SystemExit("[x] Alamat wallet tidak valid (harus base58 Solana).")
            cfg = load_config(); cfg["solana_wallet"] = addr; save_config(cfg)
            print(f"[✓] Wallet Solana disimpan: {addr}")
            print("[i] Saat bonding, pilih wallet ini di Phantom/Solflare (Devnet).")
        else:
            cur = get_saved_wallet()
            print(f"[i] Wallet tersimpan: {cur}" if cur else "[i] Belum ada wallet. Set: python bot.py wallet <ALAMAT_SOLANA>")
        return
    elif args.action == "faucet":
        print("=== Buka Faucet Devnet ===")
        open_url_android("https://faucet.solana.com/")
        wal = get_saved_wallet()
        if wal: print(f"[i] Tempel alamat ini di faucet: {wal}")
        return

if __name__ == "__main__":
    main()
