#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 lvalen91
"""Intel HEX -> Broadcom .hcd converter (stdlib only), plus verifier.

HCD = back-to-back HCI command packets WITHOUT the H4 type byte:
    opcode(u16 LE) plen(u8) params[plen]
Write_RAM  0xFC4C: params = addr(u32 LE) + data   (plen = 4 + len(data) <= 255)
Launch_RAM 0xFC4E: params = addr(u32 LE)          (0xFFFFFFFF = default entry)
btbcm_patchram() sends 0xFC2E (Download_Minidriver) itself, then replays the
file command by command, so the file must contain NO 0xFC2E.

usage:
  hex2hcd.py convert [--chunk N] [--mini-launch auto|ffffffff|ADDR] OUT.hcd IN1.hex [IN2.hex ...]
      Each input becomes Write_RAM commands followed by one Launch_RAM.
      The launch address of every input except the last one is --mini-launch
      (auto = entry from the hex EOF record offset, i.e. ext-linear<<16|offset,
      if nonzero, else 0xFFFFFFFF); the LAST input always launches 0xFFFFFFFF.
      --chunk 0 (default): one Write_RAM per hex data record (byte-identical to
      BlueZ hex2hcd for a single input). --chunk N: merge contiguous records up to N data bytes (N<=251).
  hex2hcd.py verify OUT.hcd IN1.hex [IN2.hex ...]
"""
import struct, sys, argparse

OP_WRITE, OP_LAUNCH = 0xFC4C, 0xFC4E

def parse_hex(path):
    """-> (list of (addr, bytes) in file order, eof_entry_or_None). Strict checksums."""
    recs, ext, ext_seg, eof_entry, saw_eof = [], 0, 0, None, False
    with open(path, 'r', errors='strict') as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line or line[0] == '$':      # Apple minidriver files start with a '$' line
                continue
            if line[0] != ':':
                raise ValueError(f'{path}:{ln}: bad start code')
            b = bytes.fromhex(line[1:])
            if len(b) < 5 or b[0] != len(b) - 5:
                raise ValueError(f'{path}:{ln}: length mismatch')
            if sum(b) & 0xFF:
                raise ValueError(f'{path}:{ln}: checksum error')
            n, off, t, d = b[0], b[1] << 8 | b[2], b[3], b[4:4 + b[0]]
            if saw_eof:
                raise ValueError(f'{path}:{ln}: data after EOF')
            if t == 0:
                if n:
                    recs.append(((ext << 16) + off, bytes(d)))
            elif t == 1:
                saw_eof = True
                if off:
                    eof_entry = (ext << 16) + off   # Apple encodes the entry offset here
            elif t == 4:
                ext = d[0] << 8 | d[1]
            else:
                raise ValueError(f'{path}:{ln}: unsupported record type {t}')
    if not saw_eof:
        # Apple *-Updater.hex files have no EOF record (BlueZ hex2hcd then emits no
        # Launch_RAM at all); we still append one, as every .hcd ends with it.
        print(f'note: {path}: no EOF record', file=sys.stderr)
    return recs, eof_entry

def cmd(op, params):
    assert len(params) <= 255
    return struct.pack('<HB', op, len(params)) + params

def merge(recs, chunk):
    if chunk <= 0:
        return recs
    out = []
    for a, d in recs:
        if out and out[-1][0] + len(out[-1][1]) == a and len(out[-1][1]) + len(d) <= chunk:
            out[-1] = (out[-1][0], out[-1][1] + d)
        else:
            out.append((a, d))
    return out

def build(paths, chunk, mini_launch):
    blob, expect = b'', []
    for i, p in enumerate(paths):
        recs, entry = parse_hex(p)
        recs = merge(recs, chunk)
        for a, d in recs:
            blob += cmd(OP_WRITE, struct.pack('<I', a) + d)
        if i == len(paths) - 1 or mini_launch == 'ffffffff':
            la = 0xFFFFFFFF
        elif mini_launch == 'auto':
            la = entry if entry else 0xFFFFFFFF
        else:
            la = int(mini_launch, 16)
        blob += cmd(OP_LAUNCH, struct.pack('<I', la))
        expect.append(la)
    return blob

def parse_hcd(blob):
    """-> list of (opcode, params); raises on malformation (same checks as btbcm_patchram)."""
    cmds, p = [], 0
    while p < len(blob):
        if len(blob) - p < 3:
            raise ValueError(f'truncated header at {p}')
        op, plen = struct.unpack_from('<HB', blob, p)
        p += 3
        if len(blob) - p < plen:
            raise ValueError(f'command at {p-3} overruns file')
        cmds.append((op, blob[p:p + plen]))
        p += plen
    return cmds

def image_of(recs):
    m = {}
    for a, d in recs:
        for i, x in enumerate(d):
            if a + i in m and m[a + i] != x:
                raise ValueError('overlapping hex records disagree')
            m[a + i] = x
    return m

def verify(hcd_path, hex_paths):
    blob = open(hcd_path, 'rb').read()
    cmds = parse_hcd(blob)
    errs = []
    img, stages, cur = [], 0, {}
    launches = []
    for i, (op, pr) in enumerate(cmds):
        if op == OP_WRITE:
            if len(pr) < 5:
                errs.append(f'cmd {i}: write with no data')
                continue
            a = struct.unpack_from('<I', pr)[0]
            for k, x in enumerate(pr[4:]):
                cur[a + k] = x
        elif op == OP_LAUNCH:
            if len(pr) != 4:
                errs.append(f'cmd {i}: launch plen {len(pr)} != 4')
            launches.append(struct.unpack_from('<I', pr)[0])
            img.append(cur); cur = {}
        else:
            errs.append(f'cmd {i}: unexpected opcode {op:04x}')
    if cur:
        errs.append('writes after the last launch')
    if cmds and cmds[-1][0] != OP_LAUNCH:
        errs.append('last command is not Launch_RAM')
    if len(img) != len(hex_paths):
        errs.append(f'{len(img)} launch stages in hcd vs {len(hex_paths)} hex inputs')
    else:
        for n, (im, hp) in enumerate(zip(img, hex_paths)):
            want = image_of(parse_hex(hp)[0])
            if im != want:
                errs.append(f'stage {n}: memory image differs from {hp}')
            else:
                print(f'stage {n}: {hp}: {len(want)} bytes, {hex(min(want))}..{hex(max(want)+1)} identical, launch {launches[n]:#010x}')
    if launches and launches[-1] != 0xFFFFFFFF:
        errs.append('final launch is not 0xFFFFFFFF')
    print(f'{hcd_path}: {len(cmds)} commands, {len(blob)} bytes, '
          f'{sum(1 for c in cmds if c[0]==OP_WRITE)} writes, {len(launches)} launch(es)')
    for e in errs:
        print('ERROR:', e)
    return not errs

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='mode', required=True)
    c = sp.add_parser('convert'); c.add_argument('--chunk', type=int, default=0)
    c.add_argument('--mini-launch', default='auto'); c.add_argument('out'); c.add_argument('hex', nargs='+')
    v = sp.add_parser('verify'); v.add_argument('hcd'); v.add_argument('hex', nargs='+')
    a = ap.parse_args()
    if a.mode == 'convert':
        if a.chunk > 251:
            ap.error('--chunk max 251')
        blob = build(a.hex, a.chunk, a.mini_launch.lower())
        open(a.out, 'wb').write(blob)
        return 0 if verify(a.out, a.hex) else 1
    return 0 if verify(a.hcd, a.hex) else 1

if __name__ == '__main__':
    sys.exit(main())
