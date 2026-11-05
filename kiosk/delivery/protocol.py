"""Bounded JSON shared by the native transport and the isolated server."""
import hashlib
import json
import re

MAX_METADATA_BYTES = 2 * 1024 * 1024
PROFILE = 'events-phone-lab-v1'
LIMITS = {
    'max_pixels': 2_000_000, 'max_live_bytes': 32 * 1024 * 1024,
    'per_image_ms': 5000, 'total_image_ms': 15000,
    'capture_bytes': 192 * 1024 * 1024, 'capture_files': 30003,
    'min_free_bytes': 16 * 1024 * 1024,
}


class DeliveryError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def decode(payload):
    if len(payload) > MAX_METADATA_BYTES:
        raise DeliveryError('metadata_limit', 413)

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate')
            result[key] = value
        return result

    def integer(value):
        number = int(value)
        if not -(2**63) <= number < 2**63:
            raise ValueError('integer_range')
        return number

    def invalid(value):
        raise ValueError('number_type')

    try:
        result = json.loads(payload.decode('utf-8'), object_pairs_hook=pairs, parse_int=integer,
                            parse_float=invalid, parse_constant=invalid)
        # Reject surrogate escapes even when Python's JSON parser accepts them.
        encode(result)
        if not isinstance(result, dict):
            raise ValueError('object_required')
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise DeliveryError('invalid_json') from None


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise DeliveryError('invalid_fields')


def text(value, maximum=128):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
        raise DeliveryError('invalid_identifier')
    return value


def digest(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise DeliveryError('invalid_digest')
    return value


def sha(payload):
    return hashlib.sha256(payload).hexdigest()
