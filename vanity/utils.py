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
    key_bytes = bytes.fromhex(private_key_hex)
    prefix = b'\x80'

    if compressed:
        key_bytes += b'\x01'

    payload = prefix + key_bytes
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return base58.b58encode(payload + checksum).decode()


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

    payload = b'\x00' + ripe
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]

    return base58.b58encode(payload + checksum).decode()


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
        priv = private_key_to_wif(raw_priv, compressed=False)
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
        priv = private_key_to_wif(raw_priv, compressed=False)
        private_key_bytes = bytes.fromhex(raw_priv)

        sk = ecdsa.SigningKey.from_string(private_key_bytes, curve=ecdsa.SECP256k1)
        vk = sk.get_verifying_key()
        public_key = b'\x04' + vk.to_string()

        sha = hashlib.sha256(public_key).digest()
        ripe = hashlib.new('ripemd160', sha).digest()

        payload = b'\x05' + ripe
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


# ----------------------------
# MAIN GENERATION CONTROLLER
# ----------------------------
def generate_matching(prefix="", suffix="", max_tries=500000):
    prefix = prefix.strip().upper()
    suffix = suffix.strip().upper()

    if len(prefix) > 4:
        return {"error": True, "message": "Prefix too long (max 4 characters)"}
    if len(suffix) > 4:
        return {"error": True, "message": "Suffix too long (max 4 characters)"}

    manager = multiprocessing.Manager()
    result = manager.dict()
    STOP_FLAG.value = False

    cpu_count = multiprocessing.cpu_count()

    def run_processes(target):
        processes = []
        for i in range(cpu_count):
            p = multiprocessing.Process(
                target=target,
                args=(prefix, suffix, max_tries, result, i, STOP_FLAG)
            )
            p.start()
            processes.append(p)

        # 🔥 NON-BLOCKING WAIT
        while True:
            if STOP_FLAG.value:
                for p in processes:
                    if p.is_alive():
                        p.terminate()
                break

            if not any(p.is_alive() for p in processes):
                break

            time.sleep(0.05)

        for p in processes:
            p.join(timeout=0.1)

    # --- LEGACY MODE ---
    run_processes(worker)

    if "address" in result:
        return dict(result)

    # --- P2SH FALLBACK ---
    result.clear()
    STOP_FLAG.value = False
    run_processes(worker_p2sh)

    if STOP_FLAG.value and "address" not in result:
        return {"stopped": True, "tries": None, "time": None}

    if "address" not in result:
        return {
            "error": True,
            "message": "No matching address found",
            "tries": None
        }

    return dict(result)


# ----------------------------
# EXTERNAL STOP TRIGGER
# ----------------------------
def stop_generation():
    STOP_FLAG.value = True