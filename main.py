from __future__ import annotations

import os
import re
import sys
import time
import json
import random
import datetime as dt
from typing import Dict, List, Optional, Tuple

import requests
import pytz
from eth_account import Account
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.prompt import IntPrompt, Confirm
from rich.theme import Theme
from rich.progress import Progress, SpinnerColumn, TextColumn

TZ = pytz.timezone("Asia/Jakarta")

OZONE_BASE = "https://ozone-point-system.prod.gokite.ai"
NEO_BASE = "https://neo.prod.gokite.ai"
RPC_URL = "https://rpc-testnet.gokite.ai/"
PANCAKE_RPC = "https://nodes.pancakeswap.info/"

AUTH_SECRET_HEX = "6a1c35292b7c5b769ff47d89a17e7bc4f0adfe1b462981d28e0e9f7ff20b8f8a"

AI_AGENTS: Dict[str, Dict[str, str]] = {
    "Professor":     {"service_id": "deployment_BSfolnHm0er7rNprjQWYgNhQ", "subnet": "kite_ai_labs", "room": "ProfessorRoom"},
    "Crypto Buddy":  {"service_id": "deployment_l3QYj1avTiZz2vH2daFJBGu1", "subnet": "kite_ai_labs", "room": "CryptoBuddyRoom"},
    "Sherlock":      {"service_id": "deployment_OX7sn2D0WvxGUGK8CTqsU5VJ", "subnet": "kite_ai_labs", "room": "SherlockRoom"},
    "Zane":          {"service_id": "deployment_zF2OStYBycSdlr9seHxMNlKM", "subnet": "ai_veronica", "room": "ZaneRoom"},
    "Vyn":           {"service_id": "deployment_wOzmAZlquWg8S8HbXIO4tFew", "subnet": "ai_veronica", "room": "VynRoom"},
    "Avril":         {"service_id": "deployment_KCLCuQQ85zB1xuGWdEeOZhN9", "subnet": "ai_veronica", "room": "AvrilRoom"},
    "Noa":           {"service_id": "deployment_EWs2Pqns7kau4hl3ouzZuIs6", "subnet": "ai_veronica", "room": "NoaRoom"},
    "Diane":         {"service_id": "deployment_c1PPnuoFzDKQ0O50KK0HFAkS", "subnet": "ai_veronica", "room": "DianeRoom"},
    "Sakura":        {"service_id": "deployment_KeGij2dTzbjtWLqMMWWccyGk", "subnet": "ai_veronica", "room": "SakuraRoom"},
}
AGENT_ORDER = [
    "Professor", "Crypto Buddy", "Sherlock",
    "Zane", "Vyn", "Avril", "Noa", "Diane", "Sakura",
]

TOPIC_FILES: Dict[str, str] = {
    "Professor": "pesan_professor.txt",
    "Crypto Buddy": "pesan_cryptobuddy.txt",
    "Sherlock": "pesan_sherlock.txt",
    "Zane": "pesan_zane.txt",
    "Vyn": "pesan_vyn.txt",
    "Avril": "pesan_avril.txt",
    "Noa": "pesan_noa.txt",
    "Diane": "pesan_diane.txt",
    "Sakura": "pesan_sakura.txt",
}

GLOBAL_DAILY_CHAT_CAP = 9

STAKE_MIN = 1.0
SUBNETS: Dict[str, str] = {
    "Kite AI Agents": "0xb132001567650917d6bd695d1fab55db7986e9a5",
    "Bitte":          "0xca312b44a57cc9fd60f37e6c9a343a1ad92a3b6c",
    "Bitmind":        "0xc368ae279275f80125284d16d292b650ecbbff8d",
}
SUBNET_ORDER = ["Kite AI Agents", "Bitte", "Bitmind"]
STATE_FILE = "staking_state.json"
CLAIM_AFTER_HOURS = 24
UNSTAKE_AFTER_HOURS = 24

theme = Theme({
    "ok": "bold green",
    "err": "bold red",
    "info": "cyan",
    "muted": "dim",
    "title": "bold magenta",
    "agent": "bold yellow",
    "warn": "yellow",
})
console = Console(theme=theme)

class TooManyRequestsError(Exception):
    pass

def now_jkt() -> dt.datetime:
    return dt.datetime.now(TZ)

def now_str() -> str:
    return now_jkt().strftime("%d/%m/%Y, %H:%M:%S")

def read_lines(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip().replace("\r", "") for ln in f.read().splitlines() if ln.strip()]

def is_valid_pk(pk: str) -> bool:
    pk = pk.lower()
    if pk.startswith("0x"):
        pk = pk[2:]
    return bool(re.fullmatch(r"[0-9a-f]{64}", pk))

def create_session(proxy: Optional[str]) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) KITE-AI/3.0"})
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    return s

def aes_gcm_token(message: str, secret_hex: str) -> str:
    key = bytes.fromhex(secret_hex)
    if len(key) != 32:
        raise ValueError("AUTH secret must be 32 bytes")
    iv = os.urandom(12)
    aes = AESGCM(key)
    ct = aes.encrypt(iv, message.encode("utf-8"), None)
    return (iv + ct).hex()

def sleep_seconds(sec: float):
    try:
        time.sleep(sec)
    except KeyboardInterrupt:
        console.print("\n[err]Interrupted. Exiting.[/err]")
        sys.exit(0)

def human_tdelta(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def request_json(session: requests.Session, method: str, url: str, **kwargs) -> dict:
    r = session.request(method, url, **kwargs)
    if r.status_code == 429:
        raise TooManyRequestsError("rate limited")
    data = {}
    try:
        data = r.json()
    except Exception:
        r.raise_for_status()
        return data
    err = (data.get("error") or "").lower()
    if "too many" in err or ("rate" in err and "limit" in err):
        raise TooManyRequestsError("rate limited")
    if r.status_code >= 400:
        msg = data.get("error") or f"HTTP {r.status_code}"
        raise requests.HTTPError(msg, response=r)
    return data

def rpc_eth_call_smart_account(session: requests.Session, eoa: str) -> str:
    data = "0x8cb84e18" + "0" * 24 + eoa[2:] + "4b6f5b36bb7706150b17e2eecb6e602b1b90b94a4bf355df57466626a5cb897b"
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "eth_call",
        "params": [{"data": data, "to": "0x948f52524Bdf595b439e7ca78620A8f843612df3"}, "latest"],
    }
    data = request_json(session, "POST", RPC_URL, json=payload, headers={"Content-Type": "application/json"})
    res = data.get("result", "")
    if not res or res == "0x":
        raise RuntimeError("eth_call returned empty result")
    aa = "0x" + res[-40:]
    return aa

def signin_and_login(session: requests.Session, eoa: str, aa_address: str) -> Tuple[str, str]:
    auth_token = aes_gcm_token(eoa, AUTH_SECRET_HEX)
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Authorization": auth_token,
        "Origin": "https://testnet.gokite.ai",
        "Referer": "https://testnet.gokite.ai/",
    }
    payload = {"eoa": eoa, "aa_address": aa_address}
    data = request_json(session, "POST", f"{NEO_BASE}/v2/signin", json=payload, headers=headers)
    access_token = data.get("data", {}).get("access_token", "")
    if not access_token:
        raise RuntimeError("signin: missing access_token")
    headers2 = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    body = {
        "registration_type_id": 1,
        "user_account_id": "",
        "user_account_name": "",
        "eoa_address": eoa,
        "smart_account_address": aa_address,
        "referral_code": "",
    }
    try:
        _ = request_json(session, "POST", f"{OZONE_BASE}/auth", json=body, headers=headers2)
    except requests.HTTPError as e:
        if "already exists" not in str(e).lower():
            raise
    return aa_address, access_token

def wallet_info(session: requests.Session, access_token: str) -> Tuple[str, int, int]:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    data = request_json(session, "GET", f"{OZONE_BASE}/me", headers=headers)
    prof = data.get("data", {}).get("profile", {})
    return prof.get("username", "-"), prof.get("rank", 0), prof.get("total_xp_points", 0)

def get_balances(session: requests.Session, access_token: str) -> Tuple[float, float]:
    headers = {"Authorization": f"Bearer {access_token}"}
    data = request_json(session, "GET", f"{OZONE_BASE}/me/balance", headers=headers)
    bals = data.get("data", {}).get("balances", {}) or {}
    return float(bals.get("kite", 0.0)), float(bals.get("usdt", 0.0))

def get_staked_totals(session: requests.Session, access_token: str) -> Tuple[float, float]:
    headers = {"Authorization": f"Bearer {access_token}"}
    data = request_json(session, "GET", f"{OZONE_BASE}/me/staked", headers=headers)
    d = data.get("data", {}) or {}
    return float(d.get("total_staked_amount", 0.0)), float(d.get("total_claim_reward_amount", 0.0))

def chat_ai(session: requests.Session, access_token: str, agent_name: str, eoa: str, message: str) -> dict:
    info = AI_AGENTS[agent_name]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Origin": "https://testnet.gokite.ai",
        "Referer": "https://testnet.gokite.ai/",
    }
    payload = {
        "service_id": info["service_id"],
        "subnet": info["subnet"],
        "stream": False,
        "body": {
            "roomId": info["room"],
            "userId": eoa,
            "username": eoa,
            "message": message,
            "timeDiff": 0,
            "date": "1608",
        },
    }
    return request_json(session, "POST", f"{OZONE_BASE}/agent/inference", json=payload, headers=headers)

def submit_receipt(session: requests.Session, access_token: str, aa_address: str, service_id: str, message: str, reply: str) -> str:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    body = {
        "address": aa_address,
        "service_id": service_id,
        "input": [{"type": "text/plain", "value": message}],
        "output": [{"type": "text/plain", "value": reply}],
    }
    data = request_json(session, "POST", f"{NEO_BASE}/v2/submit_receipt", json=body, headers=headers)
    rid = data.get("data", {}).get("id", "")
    if not rid:
        raise RuntimeError("submit_receipt: missing id")
    return rid

def get_inference_tx(session: requests.Session, access_token: str, report_id: str, max_retry: int = 5, wait_sec: int = 8) -> str:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    for _ in range(max_retry):
        try:
            data = request_json(session, "GET", f"{NEO_BASE}/v1/inference", params={"id": report_id}, headers=headers)
        except TooManyRequestsError:
            sleep_seconds(wait_sec)
            continue
        txh = data.get("data", {}).get("tx_hash", "")
        if txh:
            return txh
        sleep_seconds(wait_sec)
    return ""

def create_quiz(session: requests.Session, access_token: str, eoa: str) -> str:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    today = now_jkt().strftime("%Y-%m-%d")
    body = {"title": f"daily_quiz_{today}", "num": 1, "eoa": eoa}
    data = request_json(session, "POST", f"{NEO_BASE}/v2/quiz/create", json=body, headers=headers)
    qid = data.get("data", {}).get("quiz_id", "")
    if not qid:
        raise RuntimeError("quiz/create: missing quiz_id")
    return qid

def get_quiz_and_answer(session: requests.Session, access_token: str, quiz_id: str, eoa: str) -> Tuple[str, str]:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    data = request_json(session, "GET", f"{NEO_BASE}/v2/quiz/get", params={"id": quiz_id, "eoa": eoa}, headers=headers)
    questions = data.get("data", {}).get("question", [])
    if not questions:
        raise RuntimeError("quiz/get: no questions")
    first = questions[0]
    qid = first.get("question_id", "")
    ans = first.get("answer", "")
    return qid, ans

def submit_quiz(session: requests.Session, access_token: str, quiz_id: str, question_id: str, answer: str, eoa: str) -> bool:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    body = {"quiz_id": quiz_id, "question_id": question_id, "answer": answer, "finish": True, "eoa": eoa}
    data = request_json(session, "POST", f"{NEO_BASE}/v2/quiz/submit", json=body, headers=headers)
    return bool(data.get("data", {}).get("result"))

_TX_CACHE: List[str] = []
def get_random_tx_hash(session: requests.Session) -> str:
    global _TX_CACHE
    if _TX_CACHE:
        return random.choice(_TX_CACHE)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber", "params": ["latest", True]}
    try:
        data = request_json(session, "POST", PANCAKE_RPC, json=payload, headers={"Content-Type": "application/json"})
        txs = (data.get("result") or {}).get("transactions") or []
        _TX_CACHE = [tx.get("hash") for tx in txs if tx.get("hash")] or []
    except Exception:
        pass
    if not _TX_CACHE:
        return "0x" + "0"*64
    return random.choice(_TX_CACHE)

def state_load() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"accounts": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"accounts": {}}

def state_save(st: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)

def ensure_account_state(st: dict, address: str):
    if "accounts" not in st:
        st["accounts"] = {}
    if address not in st["accounts"]:
        st["accounts"][address] = {"subnets": {}}
    for name in SUBNET_ORDER:
        addr = SUBNETS[name]
        if addr not in st["accounts"][address]["subnets"]:
            st["accounts"][address]["subnets"][addr] = {
                "name": name,
                "staked": False,
                "last_stake_at": None,
                "last_claim_at": None,
                "last_unstake_at": None,
            }

def ts_now_iso() -> str:
    return now_jkt().isoformat()

def hours_since(ts_iso: Optional[str]) -> Optional[float]:
    if not ts_iso:
        return None
    try:
        t = dt.datetime.fromisoformat(ts_iso)
        if t.tzinfo is None:
            t = TZ.localize(t)
        delta = now_jkt() - t
        return delta.total_seconds() / 3600.0
    except Exception:
        return None

def delegate(session: requests.Session, access_token: str, subnet_addr: str, amount: float) -> dict:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    body = {"subnet_address": subnet_addr, "amount": amount}
    return request_json(session, "POST", f"{OZONE_BASE}/subnet/delegate", json=body, headers=headers)

def claim_rewards(session: requests.Session, access_token: str, subnet_addr: str) -> dict:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    body = {"subnet_address": subnet_addr}
    return request_json(session, "POST", f"{OZONE_BASE}/subnet/claim-rewards", json=body, headers=headers)

def undelegate(session: requests.Session, access_token: str, subnet_addr: str, amount: float) -> dict:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    body = {"subnet_address": subnet_addr, "amount": amount}
    return request_json(session, "POST", f"{OZONE_BASE}/subnet/undelegate", json=body, headers=headers)

def staking_cycle(session: requests.Session, access_token: str, address: str) -> Tuple[int, int, int]:
    st = state_load()
    ensure_account_state(st, address)
    acct = st["accounts"][address]["subnets"]
    staked_count = claimed_count = unstaked_count = 0
    try:
        kite_bal, usdt_bal = get_balances(session, access_token)
    except TooManyRequestsError:
        console.print("  ❌ [err]Chat Dengan AI Agent sudah mencapai batas maksimal, Coba Lagi Besok![/err]")
        return (0, 0, 0)
    except Exception as e:
        console.print(f"  [warn]Balance fetch error: {e}[/warn]")
        kite_bal, usdt_bal = 0.0, 0.0
    table_bal = Table(title="Balances", header_style="info")
    table_bal.add_column("Token"); table_bal.add_column("Amount", justify="right")
    table_bal.add_row("KITE", f"{kite_bal:.6f}")
    table_bal.add_row("USDT", f"{usdt_bal:.6f}")
    console.print(table_bal)
    if kite_bal >= STAKE_MIN:
        console.print(Panel("Staking Phase", border_style="info"))
        for name in SUBNET_ORDER:
            subnet = SUBNETS[name]
            row = acct[subnet]
            if not row["staked"] and kite_bal >= STAKE_MIN:
                try:
                    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as prog:
                        prog.add_task(description=f"Stake 1 KITE to {name} …", total=None)
                        data = delegate(session, access_token, subnet, 1)
                    tx = (data.get("data") or {}).get("tx_hash", "")
                    console.print(f"  ✓ [ok]Staked 1 KITE to {name}[/ok]  tx: {tx[:10]}…")
                    row["staked"] = True
                    row["last_stake_at"] = ts_now_iso()
                    staked_count += 1
                    kite_bal -= 1.0
                except TooManyRequestsError:
                    console.print("  ❌ [err]Chat Dengan AI Agent sudah mencapai batas maksimal, Coba Lagi Besok![/err]")
                    state_save(st)
                    return (staked_count, claimed_count, unstaked_count)
                except Exception as e:
                    console.print(f"  ❌ [err]Stake {name} gagal: {e}[/err]")
    else:
        console.print(Panel("Saldo < 1 KITE — Skip staking baru. Deteksi posisi staking aktif:", border_style="warn"))
        det_table = Table(header_style="info", title="Active Stakes (Countdown to 24h)")
        det_table.add_column("Subnet")
        det_table.add_column("Staked?")
        det_table.add_column("Since (hrs)", justify="right")
        det_table.add_column("To 24h", justify="right")
        for name in SUBNET_ORDER:
            subnet = SUBNETS[name]
            row = acct[subnet]
            if row["staked"]:
                h = hours_since(row["last_stake_at"]) or 0.0
                to24 = max(0, int(24*3600 - h*3600))
                det_table.add_row(name, "Yes", f"{h:.2f}", human_tdelta(to24))
            else:
                det_table.add_row(name, "No", "-", "-")
        console.print(det_table)
    console.print(Panel("Claim Phase", border_style="info"))
    for name in SUBNET_ORDER:
        subnet = SUBNETS[name]
        row = acct[subnet]
        if row["staked"]:
            try:
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as prog:
                    prog.add_task(description=f"Claim rewards @ {name} …", total=None)
                    data = claim_rewards(session, access_token, subnet)
                claim_amt = (data.get("data") or {}).get("claim_amount", 0.0)
                console.print(f"  ✓ [ok]Claim {name}[/ok] amount: {float(claim_amt):.12f}")
                row["last_claim_at"] = ts_now_iso()
                claimed_count += 1
            except TooManyRequestsError:
                console.print("  ❌ [err]Chat Dengan AI Agent sudah mencapai batas maksimal, Coba Lagi Besok![/err]")
                state_save(st)
                return (staked_count, claimed_count, unstaked_count)
            except Exception as e:
                console.print(f"  ❌ [err]Claim {name} gagal: {e}[/err]")
    console.print(Panel("Unstake Phase (≥ 24 jam)", border_style="info"))
    for name in SUBNET_ORDER:
        subnet = SUBNETS[name]
        row = acct[subnet]
        if row["staked"]:
            hrs = hours_since(row["last_stake_at"]) or 0.0
            if hrs >= UNSTAKE_AFTER_HOURS:
                try:
                    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as prog:
                        prog.add_task(description=f"Unstake 1 KITE from {name} …", total=None)
                        data = undelegate(session, access_token, subnet, 1)
                    console.print(f"  ✓ [ok]Unstaked 1 KITE from {name}[/ok]")
                    row["staked"] = False
                    row["last_unstake_at"] = ts_now_iso()
                    unstaked_count += 1
                except TooManyRequestsError:
                    console.print("  ❌ [err]Chat Dengan AI Agent sudah mencapai batas maksimal, Coba Lagi Besok![/err]")
                    state_save(st)
                    return (staked_count, claimed_count, unstaked_count)
                except requests.HTTPError as e:
                    msg = str(e)
                    if "too short" in msg.lower():
                        to24s = int(24*3600 - hrs*3600)
                        console.print(f"  ⏳ [warn]{name}: Belum 24 jam, sisa {human_tdelta(to24s)}[/warn]")
                    else:
                        console.print(f"  ❌ [err]Unstake {name} gagal: {msg}[/err]")
                except Exception as e:
                    console.print(f"  ❌ [err]Unstake {name} gagal: {e}[/err]")
            else:
                to24 = int(24*3600 - hrs*3600)
                console.print(f"  ⏳ {name}: tunggu {human_tdelta(to24)} untuk Unstake")
    try:
        kite_bal, _ = get_balances(session, access_token)
    except Exception:
        kite_bal = 0.0
    if kite_bal >= STAKE_MIN:
        console.print(Panel("Restake Phase (post-unstake)", border_style="info"))
        for name in SUBNET_ORDER:
            subnet = SUBNETS[name]
            row = acct[subnet]
            if not row["staked"] and kite_bal >= STAKE_MIN:
                try:
                    data = delegate(session, access_token, subnet, 1)
                    tx = (data.get("data") or {}).get("tx_hash", "")
                    console.print(f"  ✓ [ok]Re-staked 1 KITE to {name}[/ok]  tx: {tx[:10]}…")
                    row["staked"] = True
                    row["last_stake_at"] = ts_now_iso()
                    staked_count += 1
                    kite_bal -= 1.0
                except TooManyRequestsError:
                    console.print("  ❌ [err]Chat Dengan AI Agent sudah mencapai batas maksimal, Coba Lagi Besok![/err]")
                    state_save(st)
                    return (staked_count, claimed_count, unstaked_count)
                except Exception as e:
                    console.print(f"  ❌ [err]Re-stake {name} gagal: {e}[/err]")
    else:
        console.print("[muted]Saldo tidak cukup untuk re-stake saat ini.[/muted]")
    state_save(st)
    return staked_count, claimed_count, unstaked_count

def _send_one_chat(session: requests.Session,
                   access_token: str,
                   aa_address: str,
                   address: str,
                   agent_name: str,
                   message: str) -> Tuple[bool, bool]:
    service_id = AI_AGENTS[agent_name]["service_id"]
    try:
        resp = chat_ai(session, access_token, agent_name, address, message)
        reply = resp.get("reply", "") or "Received"
        console.print(f"   ↳ [ok]{reply}[/ok]")
        rid = submit_receipt(session, access_token, aa_address, service_id, message, reply)
        txh = get_inference_tx(session, access_token, rid, max_retry=5, wait_sec=8)
        if txh:
            console.print(f"   ↳ tx_hash: [ok]{txh}[/ok]")
        else:
            console.print("   ↳ tx_hash: [muted]pending[/muted]")
        return True, False
    except TooManyRequestsError:
        console.print("   ❌ [err]Chat Dengan AI Agent sudah mencapai batas maksimal, Coba Lagi Besok![/err]")
        return False, True
    except Exception as e:
        console.print(f"   ❌ [err]{e}[/err]")
        return False, False

def process_account(account_idx: int,
                    address: str,
                    private_key: str,
                    proxy: Optional[str],
                    chat_per_agent: int,
                    topics: Dict[str, List[str]]) -> Tuple[int, int, bool]:
    success, failed = 0, 0
    short = f"{address[:8]}...{address[-6:]}"
    console.print(Rule(title=f"[title]Account {account_idx}[/title] • {short} • {now_str()}"))
    meta_table = Table.grid(padding=1)
    meta_table.add_row("Proxy:", proxy or "[muted]-[/muted]")
    console.print(Panel(meta_table, title="Session", border_style="info"))
    session = create_session(proxy)
    try:
        aa_address = rpc_eth_call_smart_account(session, address)
        console.print(f"✓ Smart account: [ok]{aa_address[:8]}...[/ok]")
    except TooManyRequestsError:
        console.print("❌ [err]Chat Dengan AI Agent sudah mencapai batas maksimal, Coba Lagi Besok![/err]")
        return success, failed + 1, True
    except Exception as e:
        console.print(f"❌ [err]Failed to fetch smart account: {e}[/err]")
        return success, failed + 1, False
    try:
        _, access_token = signin_and_login(session, address, aa_address)
        console.print("✓ [ok]Authenticated & logged in[/ok]")
    except TooManyRequestsError:
        console.print("❌ [err]Chat Dengan AI Agent sudah mencapai batas maksimal, Coba Lagi Besok![/err]")
        return success, failed + 1, True
    except Exception as e:
        console.print(f"❌ [err]Auth/login failed: {e}[/err]")
        return success, failed + 1, False
    total_success_today = 0
    consecutive_429 = 0
    hit_global_limit = False
    for agent_name in AGENT_ORDER:
        if total_success_today >= GLOBAL_DAILY_CHAT_CAP:
            break
        pool = topics.get(agent_name, [])
        console.print(Panel(f"Chat with [agent]{agent_name}[/agent] × {chat_per_agent}", border_style="agent"))
        attempts = min(chat_per_agent, GLOBAL_DAILY_CHAT_CAP - total_success_today)
        for i in range(attempts):
            if total_success_today >= GLOBAL_DAILY_CHAT_CAP:
                break
            if agent_name == "Sherlock" and not pool:
                msg = f"What do you think of this transaction? {get_random_tx_hash(session)}"
            else:
                if not pool:
                    console.print(f"   [muted]No topics for {agent_name}[/muted]")
                    break
                msg = random.choice(pool)
            console.print(f"[muted]#{i+1}/{attempts}[/muted] → {msg}")
            ok, rate_limited = _send_one_chat(session, access_token, aa_address, address, agent_name, msg)
            if ok:
                success += 1
                total_success_today += 1
                consecutive_429 = 0
            else:
                failed += 1
                if rate_limited:
                    consecutive_429 += 1
                    if consecutive_429 >= 5:
                        hit_global_limit = True
                        break
            sleep_seconds(2)
        if hit_global_limit:
            break
    if chat_per_agent == 1 and total_success_today < GLOBAL_DAILY_CHAT_CAP and not hit_global_limit:
        console.print(Panel("Extra Attempt Round (global cap balancing)", border_style="info"))
        for agent_name in AGENT_ORDER:
            if total_success_today >= GLOBAL_DAILY_CHAT_CAP:
                break
            pool = topics.get(agent_name, [])
            if agent_name == "Sherlock" and not pool:
                msg = f"What do you think of this transaction? {get_random_tx_hash(session)}"
            else:
                if not pool:
                    continue
                msg = random.choice(pool)
            console.print(f"→ Retry {agent_name}: {msg}")
            ok, rate_limited = _send_one_chat(session, access_token, aa_address, address, agent_name, msg)
            if ok:
                success += 1
                total_success_today += 1
                consecutive_429 = 0
            else:
                failed += 1
                if rate_limited:
                    consecutive_429 += 1
                    if consecutive_429 >= 5:
                        hit_global_limit = True
                        break
            sleep_seconds(2)
    console.print(Panel("Daily Quiz", border_style="info"))
    try:
        qid = create_quiz(session, access_token, address)
        q_question_id, q_answer = get_quiz_and_answer(session, access_token, qid, address)
        ok = submit_quiz(session, access_token, qid, q_question_id, q_answer, address)
        if ok:
            console.print("✓ [ok]Quiz completed[/ok]")
            success += 1
        else:
            console.print("❌ [err]Quiz failed to submit[/err]")
            failed += 1
    except TooManyRequestsError:
        console.print("❌ [err]Chat Dengan AI Agent sudah mencapai batas maksimal, Coba Lagi Besok![/err]")
        failed += 1
    except Exception as e:
        console.print(f"❌ [err]Quiz error: {e}[/err]")
        failed += 1
    console.print(Panel("Staking Automation", border_style="title"))
    staked_c, claimed_c, unstaked_c = staking_cycle(session, access_token, address)
    try:
        uname, rank, xp = wallet_info(session, access_token)
        kite_bal, usdt_bal = get_balances(session, access_token)
        total_staked, total_claimed = get_staked_totals(session, access_token)
        stat = Table(title="Final Statistics", header_style="title", show_lines=True)
        stat.add_column("Field"); stat.add_column("Value", justify="right")
        stat.add_row("Username", uname)
        stat.add_row("Rank", str(rank))
        stat.add_row("Total XP", str(xp))
        stat.add_row("KITE Balance", f"{kite_bal:.6f}")
        stat.add_row("USDT Balance", f"{usdt_bal:.6f}")
        stat.add_row("Total Staked", f"{total_staked:.6f}")
        stat.add_row("Total Rewards (claimed)", f"{total_claimed:.6f}")
        stat.add_row("Stake Ops", f"{staked_c} staked / {claimed_c} claimed / {unstaked_c} unstaked")
        console.print(stat)
    except Exception as e:
        console.print(f"[muted]Stats error: {e}[/muted]")
    return success, failed, hit_global_limit

def run_cycle(chat_per_agent: int, use_proxy: bool) -> bool:
    acc_lines = read_lines("accounts.txt")
    if not acc_lines:
        console.print("[err]accounts.txt not found or empty! Fill one private key per line.[/err]")
        sys.exit(1)
    accounts: List[Tuple[str, str]] = []
    for i, raw in enumerate(acc_lines, 1):
        pk = raw.strip()
        pk_norm = pk if pk.lower().startswith("0x") else "0x" + pk
        if not is_valid_pk(pk_norm):
            console.print(f"[err]Invalid private key at line {i}: {pk}[/err]")
            sys.exit(1)
        try:
            acct = Account.from_key(pk_norm)
            addr = acct.address
        except Exception as e:
            console.print(f"[err]Failed deriving address at line {i}: {e}[/err]")
            sys.exit(1)
        accounts.append((addr, pk_norm))
    proxies: List[Optional[str]] = []
    if use_proxy:
        p_lines = read_lines("proxy.txt")
        if not p_lines:
            console.print("[info]proxy.txt not found or empty. Continuing without proxy.[/info]")
            proxies = [None] * len(accounts)
        else:
            for i in range(len(accounts)):
                proxies.append(p_lines[i % len(p_lines)])
    else:
        proxies = [None] * len(accounts)
    topics: Dict[str, List[str]] = {}
    for agent, fname in TOPIC_FILES.items():
        t = read_lines(fname)
        t = [x for x in t if x and all(ord(ch) < 128 for ch in x)]
        topics[agent] = t
    total_ok, total_fail = 0, 0
    hit_global_limit_any = False
    for idx, (addr, pk) in enumerate(accounts, 1):
        proxy = proxies[idx - 1] if proxies else None
        ok, fail, hit_limit = process_account(idx, addr, pk, proxy, chat_per_agent, topics)
        total_ok += ok; total_fail += fail
        if hit_limit:
            hit_global_limit_any = True
            break
    table = Table(title="Cycle Summary", header_style="title")
    table.add_column("OK", justify="right", style="ok")
    table.add_column("Failed", justify="right", style="err")
    table.add_row(str(total_ok), str(total_fail))
    console.print(table)
    return hit_global_limit_any

def countdown_to(next_time: dt.datetime):
    while True:
        now = now_jkt()
        if now >= next_time:
            break
        delta = next_time - now
        total_sec = int(delta.total_seconds())
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        console.print(f" ┊ ⏳ Waiting next cycle: [info]{h:02d}:{m:02d}:{s:02d}[/info]", end="\r")
        sleep_seconds(1)
    console.print()

def main():
    console.print(Rule(title="[title]KITE AI Auto Runner + Staking[/title]"))
    chat_per_agent = IntPrompt.ask("Masukkan jumlah chat per agent", default=1, show_default=True)
    use_proxy = Confirm.ask("Gunakan proxy?", default=False)
    while True:
        console.print(Rule(title=f"[title]Start cycle @ {now_str()}[/title]"))
        try:
            hit_limit = run_cycle(chat_per_agent, use_proxy)
        except Exception as e:
            console.print(f"[err]Uncaught error in cycle: {e}[/err]")
            hit_limit = False
        console.print(Rule(title=f"[title]Finished cycle @ {now_str()}[/title]"))
        next_run = now_jkt() + dt.timedelta(hours=24)
        countdown_to(next_run)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[err]Bye![/err]")
        sys.exit(0)
