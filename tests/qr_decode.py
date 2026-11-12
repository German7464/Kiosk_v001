"""Independent, dependency-free QR decoder used only to verify the generated
pairing QR. It reads a pristine PNG back to its text without importing the
Nayuki encoder, so it is genuine decode evidence rather than a matrix echo.

Scope: Model 2, byte/numeric/alphanumeric segments, versions 1..40, any mask
and ECC level, for a pristine image (no Reed-Solomon error correction). This is
test-only material; it is not shipped in the product.
"""
from __future__ import annotations

# ISO/IEC 18004 constant tables (not copied from Nayuki's code).
_ECC_CODEWORDS_PER_BLOCK = (
    (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
)

_NUM_BLOCKS = (
    (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
    (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
)

_ECC_FORMAT_TO_ORDINAL = {1: 0, 0: 1, 3: 2, 2: 3}

_MASKS = (
    lambda x, y: (x + y) % 2,
    lambda x, y: y % 2,
    lambda x, y: x % 3,
    lambda x, y: (x + y) % 3,
    lambda x, y: (x // 3 + y // 2) % 2,
    lambda x, y: x * y % 2 + x * y % 3,
    lambda x, y: (x * y % 2 + x * y % 3) % 2,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2,
)


def _raw_data_modules(version):
    result = (16 * version + 128) * version + 64
    if version >= 2:
        numalign = version // 7 + 2
        result -= (25 * numalign - 10) * numalign - 55
        if version >= 7:
            result -= 36
    return result


def _alignment_positions(version, size):
    if version == 1:
        return []
    numalign = version // 7 + 2
    step = (version * 8 + numalign * 3 + 5) // (numalign * 4 - 4) * 2
    result = [(size - 7 - i * step) for i in range(numalign - 1)] + [6]
    return list(reversed(result))


def _function_map(version, size):
    func = [[False] * size for _ in range(size)]

    def mark(x, y):
        if 0 <= x < size and 0 <= y < size:
            func[y][x] = True

    for i in range(size):
        mark(6, i)
        mark(i, 6)
    for (fx, fy) in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                mark(fx + dx, fy + dy)
    positions = _alignment_positions(version, size)
    num = len(positions)
    skips = {(0, 0), (0, num - 1), (num - 1, 0)}
    for i in range(num):
        for j in range(num):
            if (i, j) in skips:
                continue
            cx, cy = positions[i], positions[j]
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    mark(cx + dx, cy + dy)
    for i in range(6):
        mark(8, i)
    mark(8, 7)
    mark(8, 8)
    mark(7, 8)
    for i in range(9, 15):
        mark(14 - i, 8)
    for i in range(8):
        mark(size - 1 - i, 8)
    for i in range(8, 15):
        mark(8, size - 15 + i)
    mark(8, size - 8)
    if version >= 7:
        for i in range(18):
            a = size - 11 + i % 3
            b = i // 3
            mark(a, b)
            mark(b, a)
    return func


def _read_format(grid, size):
    bits = 0
    for i in range(6):
        bits |= (1 if grid[i][8] else 0) << i
    bits |= (1 if grid[7][8] else 0) << 6
    bits |= (1 if grid[8][8] else 0) << 7
    bits |= (1 if grid[8][7] else 0) << 8
    for i in range(9, 15):
        bits |= (1 if grid[8][14 - i] else 0) << i
    decoded = bits ^ 0x5412
    data = decoded >> 10
    ecc_format = data >> 3
    mask = data & 7
    if ecc_format not in _ECC_FORMAT_TO_ORDINAL or decoded >> 15:
        raise ValueError("format_info_unreadable")
    return _ECC_FORMAT_TO_ORDINAL[ecc_format], mask


def _deframe(data_codewords, version):
    bits = []
    for byte in data_codewords:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    pos = 0
    count_bits = 8 if version < 10 else 16

    def take(n):
        nonlocal pos
        value = 0
        for _ in range(n):
            value = (value << 1) | bits[pos]
            pos += 1
        return value

    result = []
    while True:
        mode = take(4)
        if mode == 0x0:  # terminator
            break
        if mode == 0x4:  # byte
            length = take(count_bits)
            chunk = bytearray()
            for _ in range(length):
                chunk.append(take(8))
            result.append(bytes(chunk).decode("utf-8"))
            continue
        if mode == 0x1:  # numeric
            length = take((10, 12, 14)[(version + 7) // 17])
            digits = ""
            while length >= 3:
                digits += f"{take(10):03d}"
                length -= 3
            if length == 2:
                digits += f"{take(7):02d}"
            elif length == 1:
                digits += f"{take(4):01d}"
            result.append(digits)
            continue
        if mode == 0x2:  # alphanumeric
            charset = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
            length = take((9, 11, 13)[(version + 7) // 17])
            text = ""
            while length >= 2:
                value = take(11)
                text += charset[value // 45] + charset[value % 45]
                length -= 2
            if length == 1:
                text += charset[take(6)]
            result.append(text)
            continue
        raise ValueError("unsupported_segment_mode")
    return "".join(result)


def decode_qr_image(image, scale, border=4):
    """Decode a pristine QR PNG (as rendered by our encoder) back to its text."""
    width, height = image.size
    size = width // scale - 2 * border
    if size != height // scale - 2 * border or size < 21 or (size - 17) % 4 != 0:
        raise ValueError("unexpected_grid")
    version = (size - 17) // 4

    grid = [[False] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            pixel = image.getpixel(((x + border) * scale + scale // 2, (y + border) * scale + scale // 2))
            grid[y][x] = pixel[0] < 128

    ecc_ordinal, mask = _read_format(grid, size)
    func = _function_map(version, size)

    bits = []
    for right in range(size - 1, 0, -2):
        if right <= 6:
            right -= 1
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = (right + 1) & 2 == 0
                y = (size - 1 - vert) if upward else vert
                if not func[y][x]:
                    dark = grid[y][x] ^ (_MASKS[mask](x, y) == 0)
                    bits.append(1 if dark else 0)

    rawcodewords = _raw_data_modules(version) // 8
    codewords = []
    for i in range(rawcodewords):
        byte = 0
        for bit in bits[i * 8:(i + 1) * 8]:
            byte = (byte << 1) | bit
        codewords.append(byte)

    numblocks = _NUM_BLOCKS[ecc_ordinal][version]
    blockecclen = _ECC_CODEWORDS_PER_BLOCK[ecc_ordinal][version]
    numshortblocks = numblocks - rawcodewords % numblocks
    shortblocklen = rawcodewords // numblocks

    blocks = [[0] * (shortblocklen + 1) for _ in range(numblocks)]
    pos = 0
    for i in range(shortblocklen + 1):
        for j in range(numblocks):
            if (i != shortblocklen - blockecclen) or (j >= numshortblocks):
                blocks[j][i] = codewords[pos]
                pos += 1
    assert pos == rawcodewords

    data = bytearray()
    for j in range(numblocks):
        length = shortblocklen - blockecclen + (0 if j < numshortblocks else 1)
        data.extend(blocks[j][:length])

    return _deframe(list(data), version)
