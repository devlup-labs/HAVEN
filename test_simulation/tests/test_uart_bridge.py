"""
Tests for bridge/uart_bridge.py.

Verifies:
1. Frame parsing is byte-exact identical to bridge/ring_switch.py.
2. ZMQ envelope pack/unpack is lossless.
3. Resynchronization and partial reads work cleanly.
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bridge"))
import uart_bridge
import ring_switch


def mkframe(ftype=2, src=1, dst=9, payload=b""):
    return bytes([uart_bridge.SOF, ftype, len(payload), src, dst]) + payload


def test_framing_parity_single_frame():
    f = mkframe(payload=b"\x01\x02\x03\x04")
    got_orig, used_orig = ring_switch.frames(f)
    got_new, used_new = uart_bridge.frames(f)
    assert got_orig == got_new == [f]
    assert used_orig == used_new == len(f)


def test_framing_parity_split_reads():
    f = mkframe(src=2, dst=5, payload=bytes(range(25)))
    for split in range(1, len(f)):
        orig_1, u_orig_1 = ring_switch.frames(f[:split])
        new_1, u_new_1 = uart_bridge.frames(f[:split])
        assert orig_1 == new_1 == []
        assert u_orig_1 == u_new_1

        orig_2, u_orig_2 = ring_switch.frames(f[:split] + f[split:])
        new_2, u_new_2 = uart_bridge.frames(f[:split] + f[split:])
        assert orig_2 == new_2 == [f]
        assert u_orig_2 == u_new_2 == len(f)


def test_framing_parity_corrupt_length():
    bad = bytes([uart_bridge.SOF, 2, 0xFF, 1, 2])
    good = mkframe(ftype=4, payload=b"valid")
    stream = bad + good

    orig_frames, orig_used = ring_switch.frames(stream)
    new_frames, new_used = uart_bridge.frames(stream)

    assert orig_frames == new_frames == [good]
    assert orig_used == new_used


def test_zmq_envelope_roundtrip():
    raw_frame = mkframe(ftype=1, src=3, dst=255, payload=b"\xde\xad\xbe\xef")
    env = uart_bridge.pack_envelope(3, 255, raw_frame)

    src, dst, unpacked_frame = uart_bridge.unpack_envelope(env)
    assert src == 3
    assert dst == 255
    assert unpacked_frame == raw_frame
