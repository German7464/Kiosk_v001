"""Windows CNG/DPAPI primitives; no machine trust store or private signing key."""
import base64
import ctypes as ct
from ctypes import wintypes as wt
import hashlib
import os
import struct

from kiosk.publication.exporter import PackageError


def b64(value, maximum):
    if not isinstance(value, str) or len(value) > (maximum + 2) // 3 * 4:
        raise PackageError('invalid_base64')
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError:
        raise PackageError('invalid_base64') from None
    if len(raw) > maximum or base64.b64encode(raw).decode('ascii') != value:
        raise PackageError('invalid_base64')
    return raw


def der_items(raw):
    """Strict bounded DER framing, retaining original TLV bytes for SPKI pins."""
    items, offset = [], 0
    while offset < len(raw):
        start = offset
        if offset + 2 > len(raw):
            raise PackageError('invalid_der')
        tag, size = raw[offset:offset + 2]
        offset += 2
        if size & 128:
            count = size & 127
            if not 1 <= count <= 4 or offset + count > len(raw) or raw[offset] == 0:
                raise PackageError('invalid_der')
            size = int.from_bytes(raw[offset:offset + count], 'big')
            offset += count
            if size < 128:
                raise PackageError('invalid_der')
        if offset + size > len(raw):
            raise PackageError('invalid_der')
        items.append((tag, raw[offset:offset + size], raw[start:offset + size]))
        offset += size
    return items


def sequence(raw):
    values = der_items(raw)
    if len(values) != 1 or values[0][0] != 0x30:
        raise PackageError('invalid_der')
    return der_items(values[0][1])


def certificate_spki(raw):
    try:
        cert = sequence(raw)
        tbs = sequence(cert[0][2])
        item = tbs[6 if tbs[0][0] == 0xa0 else 5]
        if item[0] != 0x30:
            raise PackageError('invalid_der')
        return item[2]
    except IndexError:
        raise PackageError('invalid_der') from None


def rsa_parameters(spki):
    parts = sequence(spki)
    if (len(parts) != 2 or parts[0][2] != bytes.fromhex('300d06092a864886f70d0101010500') or
            parts[1][0] != 3 or not parts[1][1].startswith(b'\x00')):
        raise PackageError('invalid_group_key')
    numbers = sequence(parts[1][1][1:])
    if len(numbers) != 2 or any(item[0] != 2 for item in numbers):
        raise PackageError('invalid_group_key')
    modulus, exponent = numbers[0][1], numbers[1][1]
    if len(modulus) != 385 or modulus[0] != 0 or modulus[1] < 128 or exponent != b'\x01\x00\x01':
        raise PackageError('invalid_group_key')
    return modulus[1:], exponent


def verify_signature(spki, message, signature):
    modulus, exponent = rsa_parameters(spki)
    if len(signature) != 384 or os.name != 'nt':
        raise PackageError('signature_refused')
    api = ct.WinDLL('bcrypt.dll')
    handle, key = ct.c_void_p(), ct.c_void_p()
    api.BCryptOpenAlgorithmProvider.argtypes = [ct.POINTER(ct.c_void_p), wt.LPCWSTR, wt.LPCWSTR, wt.ULONG]
    api.BCryptImportKeyPair.argtypes = [ct.c_void_p, ct.c_void_p, wt.LPCWSTR, ct.POINTER(ct.c_void_p), ct.c_void_p, wt.ULONG, wt.ULONG]
    api.BCryptVerifySignature.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_void_p, wt.ULONG, ct.c_void_p, wt.ULONG, wt.ULONG]
    api.BCryptDestroyKey.argtypes = [ct.c_void_p]
    api.BCryptCloseAlgorithmProvider.argtypes = [ct.c_void_p, wt.ULONG]

    class Padding(ct.Structure):
        _fields_ = [('algorithm', wt.LPCWSTR)]

    blob = struct.pack('<6I', 0x31415352, 3072, 3, 384, 0, 0) + exponent + modulus
    try:
        if api.BCryptOpenAlgorithmProvider(ct.byref(handle), 'RSA', None, 0) != 0:
            raise PackageError('crypto_unavailable')
        if api.BCryptImportKeyPair(handle, None, 'RSAPUBLICBLOB', ct.byref(key), blob, len(blob), 0) != 0:
            raise PackageError('invalid_group_key')
        digest = hashlib.sha256(message).digest()
        padding = Padding('SHA256')
        if api.BCryptVerifySignature(key, ct.byref(padding), digest, len(digest), signature, len(signature), 2) != 0:
            raise PackageError('signature_refused')
    finally:
        if key.value:
            api.BCryptDestroyKey(key)
        if handle.value:
            api.BCryptCloseAlgorithmProvider(handle, 0)


def protect(raw, *, decrypt=False):
    if os.name != 'nt' or len(raw) > 8 * 1024 * 1024:
        raise PackageError('native_state_refused')

    class Blob(ct.Structure):
        _fields_ = [('size', wt.DWORD), ('data', ct.POINTER(ct.c_ubyte))]

    buffer = (ct.c_ubyte * len(raw)).from_buffer_copy(raw)
    source, target = Blob(len(raw), buffer), Blob()
    api = ct.WinDLL('crypt32.dll', use_last_error=True)
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    fn.argtypes = [ct.POINTER(Blob), ct.c_void_p, ct.c_void_p, ct.c_void_p, ct.c_void_p, wt.DWORD, ct.POINTER(Blob)]
    if not fn(ct.byref(source), None, None, None, None, 1, ct.byref(target)):
        raise PackageError('native_state_refused')
    kernel = ct.WinDLL('kernel32.dll')
    kernel.LocalFree.argtypes = [ct.c_void_p]
    try:
        return ct.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def boot_clock():
    if os.name != 'nt':
        raise PackageError('unsupported_client_platform')
    data = ct.create_string_buffer(64)
    api = ct.WinDLL('ntdll.dll')
    if api.NtQuerySystemInformation(90, data, 64, None) != 0:
        raise PackageError('clock_unavailable')
    tick = ct.WinDLL('kernel32.dll').GetTickCount64
    tick.restype = ct.c_ulonglong
    return data.raw[:16].hex(), tick()
