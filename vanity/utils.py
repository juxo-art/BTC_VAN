import time
import multiprocessing
import os
import hashlib
import ecdsa
import base58

# Create a Manager at import-time so Manager.Value is truly process-shared.
# This is more robust than a raw multiprocessing.Value across different start methods.
try:
    MANAGER = multiprocessing.Manager()
    STOP_FLAG = MANAGER.Value('b', False)
except Exception:
    # If Manager creation fails for any reason (very rare), fall back to a plain Value.
    STOP_FLAG = multiprocessing.Value('b', False)


def private_key_to_address(private_key_hex):
    """Return legacy P2PKH (1...) address from private-key hex."""
    private_key_bytes = bytes.fromhex(private_key_hex)
    sk = ecdsa.SigningKey.from_string(private_key_bytes, curve=ecdsa.SECP256k1)
    vk = sk.get_verifying_key()
    public_key = b'\04' + vk.to_string()
    sha = hashlib.sha256(public_key).digest()
    ripe = hashlib.new('ripemd160', sha).digest()
    prefix = b'\x00'  # Mainnet P2PKH
    payload = prefix + ripe
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    final = payload + checksum
    return base58.b58encode(final).decode()


def generate_private_key():
    return os.urandom(32).hex()


# ---------- worker functions ----------
def worker_legacy(prefix, suffix, max_tries, return_dict, worker_id, stop_flag):
    tries = 0
    start_time = time.time()
    # core = address without leading '1', uppercase for case-insensitive matching
    while tries < max_tries:
        if stop_flag.value:
            return
        priv = generate_private_key()
        addr = private_key_to_address(priv)
        # core portion used for matching (strip the leading '1' common to P2PKH)
        core = addr[1:].upper()

        # prefix/suffix matching (user provides uppercase or lowercase; comparison is uppercase)
        if prefix and not core.startswith(prefix):
            tries += 1
            continue
        if suffix and not core.endswith(suffix):
            tries += 1
            continue

        # success
        return_dict.update({
            "address": addr,
            "private_key": priv,
            "tries": tries + 1,
            "time": round(time.time() - start_time, 2),
            "mode": "Legacy (1...)",
        })
        stop_flag.value = True
        return

    return


def worker_p2sh(prefix, suffix, max_tries, return_dict, worker_id, stop_flag):
    tries = 0
    start_time = time.time()
    while tries < max_tries:
        if stop_flag.value:
            return
        priv = generate_private_key()
        private_key_bytes = bytes.fromhex(priv)
        sk = ecdsa.SigningKey.from_string(private_key_bytes, curve=ecdsa.SECP256k1)
        vk = sk.get_verifying_key()
        public_key = b'\04' + vk.to_string()
        sha = hashlib.sha256(public_key).digest()
        ripe = hashlib.new('ripemd160', sha).digest()
        payload = b'\x05' + ripe  # P2SH (3...)
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
            "mode": "P2SH (3...)",
        })
        stop_flag.value = True
        return

    return


# ---------- controller ----------
def generate_matching(prefix="", suffix="", max_tries=500000):
    """
    Return a dict with either:
      - result keys: address, private_key, tries, time, mode
      - stopped: True and tries/time keys
      - error: True + message + tries
    The function uses a Manager().dict() so results are visible between processes.
    """
    prefix = (prefix or "").strip().upper()
    suffix = (suffix or "").strip().upper()

    # safety limits to keep runtime reasonable on shared hosts
    if len(prefix) > 8:
        return {"error": True, "message": "Prefix too long (use shorter strings).", "tries": 0}
    if len(suffix) > 8:
        return {"error": True, "message": "Suffix too long (use shorter strings).", "tries": 0}

    # Reset shared stop flag before starting
    try:
        STOP_FLAG.value = False
    except Exception:
        # If STOP_FLAG can't be reset for some reason, return an error
        return {"error": True, "message": "Internal error resetting stop flag.", "tries": 0}

    # Use a Manager dict for shared result
    try:
        manager = MANAGER if "MANAGER" in globals() else multiprocessing.Manager()
    except Exception:
        manager = multiprocessing.Manager()
    result = manager.dict()

    # Create an appropriate multiprocessing context for this platform.
    # On many Linux systems 'fork' is available and faster; on some environments use 'spawn'.
    ctx_name = 'fork' if hasattr(multiprocessing, 'get_context') and os.name == 'posix' else 'spawn'
    try:
        ctx = multiprocessing.get_context(ctx_name)
    except Exception:
        ctx = multiprocessing.get_context('spawn')

    cpu_count = max(1, min(4, multiprocessing.cpu_count()))  # limit to avoid overloading shared hosts

    # Start legacy workers (1...)
    processes = []
    for i in range(cpu_count):
        p = ctx.Process(
            target=worker_legacy,
            args=(prefix, suffix, max_tries, result, i, STOP_FLAG)
        )
        processes.append(p)
        p.start()

    for p in processes:
        p.join()

    if "address" in result:
        return dict(result)

    # If no legacy match, try P2SH fallback (3...)
    result.clear()
    try:
        STOP_FLAG.value = False
    except Exception:
        STOP_FLAG.value = False

    processes = []
    for i in range(cpu_count):
        p = ctx.Process(
            target=worker_p2sh,
            args=(prefix, suffix, max_tries, result, i, STOP_FLAG)
        )
        processes.append(p)
        p.start()

    for p in processes:
        p.join()

    # If the stop flag was triggered during work but there is no address: user stopped
    if STOP_FLAG.value and "address" not in result:
        return {
            "stopped": True,
            "tries": max_tries * cpu_count * 2,
            "time": None
        }

    if "address" not in result:
        return {
            "error": True,
            "message": "No matching address found. Try a shorter/custom prefix or suffix.",
            "tries": max_tries * cpu_count * 2
        }

    return dict(result)


# ---------- external controls ----------
def stop_generation():
    """Set the shared stop flag. Call this from your stop AJAX endpoint."""
    try:
        STOP_FLAG.value = True
    except Exception:
        pass


def reset_stop():
    """Reset the shared stop flag to False. Call this before starting a new generation."""
    try:
        STOP_FLAG.value = False
    except Exception:
        pass