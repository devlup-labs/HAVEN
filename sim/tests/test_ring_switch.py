"""
Unit tests for the ring switch's frame parser and config handling.

The parser is the one piece of the switch that touches untrusted bytes: Renode
delivers UART data in arbitrary chunks, so frames arrive split at any offset and
may contain stray bytes. A wrong bound there throws IndexError on the first
partial read and kills the run, which is how the N=3 bring-up originally failed.

Run: pytest sim/tests/
"""
import importlib.util
from pathlib import Path
import pytest

_SWITCH = Path(__file__).resolve().parents[2] / "bridge" / "ring_switch.py"
_spec = importlib.util.spec_from_file_location("ring_switch", _SWITCH)
ring_switch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ring_switch)

frames = ring_switch.frames


def mkframe(ftype=2, src=1, dst=9, payload=b""):
    """Build a frame exactly as firmware/src/haven_link.c emits it."""
    return bytes([ring_switch.SOF, ftype, len(payload), src, dst]) + payload


# ------------------------------------------------------------------ happy path

def test_single_frame():
    f = mkframe(payload=b"\x01\x02\x03")
    got, used = frames(f)
    assert got == [f]
    assert used == len(f)


def test_two_frames_in_one_read():
    a, b = mkframe(src=1, payload=b"ab"), mkframe(src=9, payload=b"cde")
    got, used = frames(a + b)
    assert got == [a, b]
    assert used == len(a) + len(b)


def test_zero_length_payload():
    """HEARTBEAT-like frames still carry a payload, but len=0 must not hang."""
    f = mkframe(ftype=4, payload=b"")
    got, _ = frames(f)
    assert got == [f]


# ------------------------------------------------------- partial reads / resync

@pytest.mark.parametrize("split", [1, 2, 3, 4, 5, 6, 7, 8])
def test_frame_split_across_reads(split):
    """A frame arriving one byte at a time must reassemble exactly."""
    f = mkframe(payload=bytes(range(20)))
    got, used = frames(f[:split])
    assert got == [], "incomplete frame must not be emitted"
    assert used < split, "must keep the partial frame buffered"

    got2, used2 = frames(f[:split] + f[split:])
    assert got2 == [f]
    assert used2 == len(f)


def test_three_way_split():
    f = mkframe(payload=bytes(range(30)))
    out, tail = [], f
    while tail:
        out, used = frames(tail)
        tail = tail[used:]
        if not out and used == 0:
            break
    assert out == [f]


def test_garbage_before_frame_is_resynced():
    f = mkframe(payload=b"\xaa\xbb")
    got, _ = frames(b"\x00\x11\xff" + f)
    assert got == [f], "must resync on SOF and skip leading junk"


def test_embedded_sof_in_payload_is_not_resynced():
    """The parser uses length, not SOF scanning, once a header is parsed."""
    payload = bytes([ring_switch.SOF]) * 4
    f = mkframe(ftype=3, payload=payload)
    got, _ = frames(f)
    assert got == [f]


def test_corrupt_length_resyncs_to_next_frame():
    """A length byte above MAX_PAYLOAD must not swallow the following frame."""
    bad = bytes([ring_switch.SOF, 2, 0xFF, 1, 2])
    good = mkframe(ftype=4, payload=b"ok")
    got, _ = frames(bad + good)
    assert got == [good]


def test_bare_sof_at_end_does_not_raise():
    """Regression: buf[s+2] was read before its index was known to exist."""
    for tail in (b"\xa5", b"\xa5\x02", b"\xa5\x02\x05"):
        got, used = frames(tail)
        assert got == []
        assert used == 0, "partial header must stay buffered, not be consumed"


def test_header_only_prefix_of_every_length():
    """No prefix of a header may raise or be dropped."""
    f = mkframe(ftype=2, src=3, dst=4, payload=b"\xde\xad")
    for n in range(len(f)):
        got, _ = frames(f[:n])
        assert got == []


def test_no_data():
    got, used = frames(b"")
    assert got == [] and used == 0


def test_junk_only_consumed_entirely():
    got, used = frames(b"\x01\x02\x03")
    assert got == [] and used == 3


# ----------------------------------------------------------------- config bits

def test_parse_ring_order_splits_spaces():
    assert ring_switch.parse_ring_order("1 9 5") == [1, 9, 5]


def test_parse_ring_order_rejects_too_few():
    with pytest.raises(ValueError):
        ring_switch.parse_ring_order("1 2")


def test_parse_ring_order_rejects_duplicates():
    with pytest.raises(ValueError):
        ring_switch.parse_ring_order("1 2 2 3")


def test_config_strips_quotes_and_comments(tmp_path):
    cfg = tmp_path / "c.conf"
    cfg.write_text(
        '# comment\n'
        'NUM_NODES=3\n'
        'RING_ORDER="1 9 5"\n'
        'HOP_DELAY_MS=20   # trailing comment\n'
    )
    parsed = ring_switch.load_config(cfg)
    assert parsed["NUM_NODES"] == "3"
    assert parsed["RING_ORDER"] == "1 9 5", "quotes must be stripped"
    assert parsed["HOP_DELAY_MS"] == "20", "trailing comment must be stripped"


def test_shipped_config_is_self_consistent():
    """The committed config must describe a ring that can actually form."""
    root = Path(__file__).resolve().parents[2]
    cfg = ring_switch.load_config(root / "haven_ring.conf")
    n = int(cfg["NUM_NODES"])
    order = ring_switch.parse_ring_order(cfg["RING_ORDER"])[:n]
    assert len(order) == n, "RING_ORDER must supply at least NUM_NODES entries"
    assert len(set(order)) == n, "no duplicate nodes"

    defines = ring_switch.read_firmware_defines(root / "firmware" / "include" / "haven_config.h")
    k, m = defines["HAVEN_NUM_SPACES"], defines["HAVEN_M_SPACES"]
    # Raises SystemExit with a clear message if any adjacent pair cannot link.
    ring_switch.validate(order, k, m, bytes(range(32)))