import time
import os
import hashlib
import ecdsa
import base58

# Single global stop flag (Render-compatible)
STOP_FLAG = False


def reset_stop_flag():
    global STOP_FLAG
    STOP_FLAG = False


def stop_generation():
    global STOP_FLAG
    STOP_FLAG = True


def private_key_to_address(private_key_hex):
    """Return legacy P2PKH (starts with 1)"""
    private_key_bytes = bytes.fromhex(private_key_hex)
    sk = ecdsa.SigningKey.from_string(private_key_bytes, curve=ecdsa.SECP256k1)
    vk = sk.get_verifying_key()
    public_key = b'\04' + vk.to_string()

    sha = hashlib.sha256(public_key).digest()
    ripe = hashlib.new("ripemd160", sha).digest()

    payload = b'\x00' + ripe
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    final = payload + checksum
    return base58.b58encode(final).decode()


def private_key_to_p2sh_address(private_key_hex):
    """Return P2SH (starts with 3)"""
    private_key_bytes = bytes.fromhex(private_key_hex)
    sk = ecdsa.SigningKey.from_string(private_key_bytes, curve=ecdsa.SECP256k1)
    vk = sk.get_verifying_key()
    public_key = b'\04' + vk.to_string()

    sha = hashlib.sha256(public_key).digest()
    ripe = hashlib.new("ripemd160", sha).digest()

    payload = b'\x05' + ripe
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    final = payload + checksum
    return base58.b58encode(final).decode()


def generate_private_key():
    return os.urandom(32).hex()


def search(prefix, suffix, max_tries, address_type="legacy"):
    """
    Single-threaded search engine for Render.com compatibility.
    """
    global STOP_FLAG
    tries = 0
    start = time.time()

    while tries < max_tries:
        if STOP_FLAG:
            return {
                "stopped": True,
                "tries": tries,
                "time": round(time.time() - start, 2)
            }

        priv = generate_private_key()

        # Generate address type
        if address_type == "legacy":
            addr = private_key_to_address(priv)
        else:
            addr = private_key_to_p2sh_address(priv)

        core = addr[1:].upper()
        up_pre = prefix.upper()
        up_suf = suffix.upper()

        # prefix check
        if up_pre and not core.startswith(up_pre):
            tries += 1
            continue

        # suffix check
        if up_suf and not core.endswith(up_suf):
            tries += 1
            continue

        # FOUND
        return {
            "address": addr,
            "private_key": priv,
            "tries": tries + 1,
            "time": round(time.time() - start, 2)
        }

    return None


def generate_matching(prefix="", suffix="", max_tries=200000):
    """
    Main generator (Render compatible)
    """

    prefix = (prefix or "").upper()
    suffix = (suffix or "").upper()

    # Limits for safety
    if len(prefix) > 8:
        return {"error": True, "message": "Prefix too long.", "tries": 0}
    if len(suffix) > 8:
        return {"error": True, "message": "Suffix too long.", "tries": 0}

    reset_stop_flag()

    # --- Try Legacy (1...) ---
    result = search(prefix, suffix, max_tries, address_type="legacy")

    if result and "address" in result:
        result["mode"] = "Legacy (1...)"
        return result

    if result and result.get("stopped"):
        return result

    # --- Try P2SH (3...) ---
    result = search(prefix, suffix, max_tries, address_type="p2sh")

    if result and "address" in result:
        result["mode"] = "P2SH (3...)"
        return result

    if result and result.get("stopped"):
        return result

    return {
        "error": True,
        "message": "No match found. Try shorter prefix/suffix.",
        "tries": max_tries * 2
    }