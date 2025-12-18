import time
import multiprocessing
import os
import hashlib
import ecdsa
import base58  # ensure base58 is installed (pip install base58)

# ----------------------------
# GLOBAL STOP FLAG
# ----------------------------
STOP_FLAG = multiprocessing.Value('b', False)


# ----------------------------
# HELPER: Convert hex private key to WIF
# ----------------------------
def private_key_to_wif(private_key_hex, compressed=False):
    """
    Convert a hex private key to WIF format.
    compressed: True if the corresponding public key should be compressed (starts with K/L)
    """
    key_bytes = bytes.fromhex(private_key_hex)
    prefix = b'\x80'  # Bitcoin mainnet prefix

    if compressed:
        key_bytes += b'\x01'

    payload = prefix + key_bytes
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    wif = base58.b58encode(payload + checksum).decode()
    return wif


# ----------------------------
# FAST BTC ADDRESS GENERATOR (Legacy 1...)
# ----------------------------
def private_key_to_address(private_key_hex):
    private_key_bytes = bytes.fromhex(private_key_hex)

    sk = ecdsa.SigningKey.from_string(private_key_bytes, curve=ecdsa.SECP256k1)
    vk = sk.get_verifying_key()

    public_key = b'\04' + vk.to_string()

    sha = hashlib.sha256(public_key).digest()
    ripe = hashlib.new('ripemd160', sha).digest()

    prefix = b'\x00'  # Legacy P2PKH
    payload = prefix + ripe

    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    final = payload + checksum

    return base58.b58encode(final).decode()


def generate_private_key():
    return os.urandom(32).hex()


# ----------------------------
# WORKER FOR LEGACY MODE
# ----------------------------
def worker(prefix, suffix, max_tries, return_dict, worker_id, stop_flag):
    tries = 0
    start_time = time.time()

    while tries < max_tries:
        if stop_flag.value:
            return

        raw_priv = generate_private_key()
        priv = private_key_to_wif(raw_priv, compressed=False)  # Standard WIF for Legacy addresses
        addr = private_key_to_address(raw_priv)

        core = addr[1:].upper()

        if prefix and not core.startswith(prefix):
            tries += 1
            continue
        if suffix and not core.endswith(suffix):
            tries += 1
            continue

        return_dict.update({
            "address": addr,
            "private_key": priv,
            "tries": tries + 1,
            "time": round(time.time() - start_time, 2),
            "mode": "Legacy (1...)"
        })

        stop_flag.value = True
        return

    return


# ----------------------------
# WORKER FOR P2SH FALLBACK (3...)
# ----------------------------
def worker_p2sh(prefix, suffix, max_tries, return_dict, worker_id, stop_flag):
    tries = 0
    start_time = time.time()

    while tries < max_tries:
        if stop_flag.value:
            return

        raw_priv = generate_private_key()
        priv = private_key_to_wif(raw_priv, compressed=False)  # Standard WIF for P2SH
        private_key_bytes = bytes.fromhex(raw_priv)
        sk = ecdsa.SigningKey.from_string(private_key_bytes, curve=ecdsa.SECP256k1)
        vk = sk.get_verifying_key()
        public_key = b'\x04' + vk.to_string()

        sha = hashlib.sha256(public_key).digest()
        ripe = hashlib.new('ripemd160', sha).digest()

        payload = b'\x05' + ripe  # P2SH
        checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        addr = base58.b58encode(payload + checksum).decode()

        core = addr[1:].upper()

        if prefix and not core.startswith(prefix):
            tries += 1
            continue
        if suffix and not core.endswith(suffix):
            tries += 1
            continue

        return_dict.update({
            "address": addr,
            "private_key": priv,
            "tries": tries + 1,
            "time": round(time.time() - start_time, 2),
            "mode": "P2SH (3...)"
        })
        stop_flag.value = True
        return

    return


# ----------------------------
# MAIN GENERATION CONTROLLER
# ----------------------------
def generate_matching(prefix="", suffix="", max_tries=500000):
    prefix = prefix.strip().upper()
    suffix = suffix.strip().upper()

    # ----------------------------
    # LENGTH CHECKS
    # ----------------------------
    if len(prefix) > 4:
        return {"error": True, "message": "Prefix too long, must be 4 characters or less to increase the chance of finding the matching address"}
    if len(suffix) > 4:
        return {"error": True, "message": "Suffix too long, must be 4 characters or less  to increase the chance of finding the matching address"}

    manager = multiprocessing.Manager()
    result = manager.dict()
    STOP_FLAG.value = False

    cpu_count = multiprocessing.cpu_count()

    # --- LEGACY MODE ---
    processes = []
    for i in range(cpu_count):
        p = multiprocessing.Process(
            target=worker,
            args=(prefix, suffix, max_tries, result, i, STOP_FLAG)
        )
        processes.append(p)
        p.start()

    for p in processes:
        p.join()

    if "address" in result:
        return dict(result)

        # --- P2SH FALLBACK ---
    result.clear()
    STOP_FLAG.value = False
    processes = []
    for i in range(cpu_count):
        p = multiprocessing.Process(
            target=worker_p2sh,
            args=(prefix, suffix, max_tries, result, i, STOP_FLAG)
        )
        processes.append(p)
        p.start()

    for p in processes:
        p.join()

    if STOP_FLAG.value and "address" not in result:
        return {
            "stopped": True,
            "tries": max_tries * cpu_count * 2,
            "time": None
        }

    if "address" not in result:
        return {
            "error": True,
            "message": "No matching address found! Customize prefix/suffix and try again.",
            "tries": max_tries * cpu_count * 2
        }

    return dict(result)


# ----------------------------
# EXTERNAL STOP TRIGGER
# ----------------------------
def stop_generation():
    STOP_FLAG.value = True