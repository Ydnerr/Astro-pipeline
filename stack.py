#!/usr/bin/env python3
"""stack.py - stacker foto astro sederhana (align bintang + average).

Input : folder berisi frame (JPG/PNG/TIFF)
Output: TIFF sRGB 16-bit, siap jadi <nama>.tif untuk astro-pipeline

Cara kerja (mode average):
  1. Deteksi bintang di tiap frame (gambar diperkecil, DoG + local maxima).
  2. Lacak bintang antar frame tetangga (optical flow), fit transformasi
     similarity pakai RANSAC, lalu perhalus langsung ke frame referensi.
  3. Warp tiap frame ke referensi, jumlahkan bertahap (hemat RAM), bagi bobot.
  4. Opsional: mask langit supaya foreground tidak blur (--mask / --auto-mask).

Mode trail: ambil piksel paling terang dari semua frame, tanpa align
(untuk star trail).

Dependensi: numpy, opencv-python, tifffile.
"""
import argparse
import os
import sys

import cv2
import numpy as np
import tifffile

EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
LK = dict(
    winSize=(31, 31),
    maxLevel=3,
    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
)


def log(*a):
    print(*a, flush=True)


def list_frames(folder):
    return sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in EXTS
    )


def load_bgr(path):
    """Baca frame sebagai float32 BGR 0..1."""
    img = cv2.imread(path, cv2.IMREAD_COLOR | cv2.IMREAD_ANYDEPTH)
    if img is None:
        raise IOError(f"tidak bisa membaca {path}")
    scale = 65535.0 if img.dtype == np.uint16 else 255.0
    return img.astype(np.float32) / scale


def load_gray_small(path, size):
    img = load_bgr(path)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, size, interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------- bintang

def prep(g):
    """Gambar abu-abu float -> (respons DoG, versi 8-bit untuk optical flow)."""
    dog = cv2.GaussianBlur(g, (0, 0), 1.2) - cv2.GaussianBlur(g, (0, 0), 6.0)
    hi = max(float(np.percentile(dog, 99.95)), 1e-6)
    u8 = np.clip(dog / hi * 255.0, 0, 255).astype(np.uint8)
    return dog, u8


def detect_stars(dog, excl, max_stars):
    med = float(np.median(dog))
    mad = float(np.median(np.abs(dog - med))) * 1.4826
    thr = med + max(6.0 * mad, 0.01)
    local_max = cv2.dilate(dog, np.ones((7, 7), np.uint8))
    peaks = (dog >= local_max) & (dog > thr)
    peaks[:20, :] = peaks[-20:, :] = False
    peaks[:, :20] = peaks[:, -20:] = False
    if excl is not None:
        peaks &= ~excl
    ys, xs = np.nonzero(peaks)
    if len(xs) == 0:
        return np.zeros((0, 1, 2), np.float32)
    order = np.argsort(-dog[ys, xs])[:max_stars]
    pts = np.stack([xs[order], ys[order]], axis=1).astype(np.float32)
    return pts.reshape(-1, 1, 2)


def track(a8, b8, pts):
    """Lacak pts dari gambar a ke b, buang yang gagal cek maju-mundur."""
    if len(pts) == 0:
        return pts, pts
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(a8, b8, pts, None, **LK)
    back, st2, _ = cv2.calcOpticalFlowPyrLK(b8, a8, nxt, None, **LK)
    d = np.linalg.norm(back - pts, axis=2).ravel()
    ok = (st.ravel() == 1) & (st2.ravel() == 1) & (d < 1.0)
    return pts[ok], nxt[ok]


def fit(src, dst, min_inliers=12, thr=1.5):
    """Similarity src->dst (RANSAC). Return (3x3, jumlah inlier, rms) atau None."""
    if len(src) < min_inliers:
        return None
    M, inl = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=thr,
        maxIters=3000, confidence=0.999,
    )
    if M is None:
        return None
    inl = inl.ravel().astype(bool)
    n = int(inl.sum())
    if n < min_inliers:
        return None
    pred = cv2.transform(src, M)
    rms = float(np.sqrt(np.mean(np.sum((pred - dst) ** 2, axis=2).ravel()[inl])))
    return np.vstack([M, [0, 0, 1]]), n, rms


def estimate_transforms(smalls, max_stars_log=True):
    """smalls: list (u8, pts). Return dict index -> (T 3x3 ke frame referensi, n, rms)."""
    n = len(smalls)
    r = n // 2
    ref_u8, ref_pts = smalls[r]
    sh, sw = ref_u8.shape
    result = {r: (np.eye(3), len(ref_pts), 0.0)}

    def sweep(indices):
        prev = r
        for k in indices:
            u8, _ = smalls[k]
            a8, a_pts = smalls[prev]
            pa, pb = track(a8, u8, a_pts)          # prev -> k
            f = fit(pb, pa)                          # k -> prev
            if f is None:
                log(f"  frame {k}: align gagal, dilewati")
                continue
            T = result[prev][0] @ f[0]               # k -> referensi
            # perhalus langsung ke referensi (kurangi drift)
            warped = cv2.warpAffine(u8, T[:2], (sw, sh))
            qa, qb = track(ref_u8, warped, ref_pts)  # ref -> warped
            g = fit(qb, qa)                          # warped -> ref
            if g is not None:
                T = g[0] @ T
                f = g
            result[k] = (T, f[1], f[2])
            prev = k

    sweep(range(r + 1, n))
    sweep(range(r - 1, -1, -1))
    return result


# ------------------------------------------------------------------- mask

def auto_mask_small(grays):
    """Heuristik: foreground = area gelap jauh di bawah level langit.
    Return float32 (1 = langit, 0 = foreground)."""
    g = np.mean(grays, axis=0).astype(np.float32)
    L = cv2.GaussianBlur(g, (0, 0), 5)
    sky_level = float(np.percentile(L, 80))
    fg = (L < 0.5 * sky_level).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cnt, lab, stats, _ = cv2.connectedComponentsWithStats(fg)
    keep = np.zeros_like(fg)
    for i in range(1, cnt):
        if stats[i, cv2.CC_STAT_AREA] > 0.002 * fg.size:
            keep[lab == i] = 1
    keep = cv2.dilate(keep, np.ones((9, 9), np.uint8))
    return 1.0 - keep.astype(np.float32)


def feather(m, sigma):
    return np.clip(cv2.GaussianBlur(m, (0, 0), sigma), 0, 1)


# ------------------------------------------------------------------- main

def write_tiff(path, rgb01, compress=True):
    arr = (np.clip(rgb01, 0, 1) * 65535.0 + 0.5).astype(np.uint16)
    tifffile.imwrite(path, arr, photometric="rgb",
                     compression="zlib" if compress else None)


def stack_trail(paths, resize):
    out = None
    for i, p in enumerate(paths, 1):
        img = load_bgr(p)
        if resize != 1.0:
            img = cv2.resize(img, None, fx=resize, fy=resize, interpolation=cv2.INTER_AREA)
        out = img if out is None else np.maximum(out, img, out=out)
        log(f"  [{i}/{len(paths)}] {os.path.basename(p)}")
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def stack_average(paths, args):
    first = load_bgr(paths[0])
    H0, W0 = first.shape[:2]
    del first
    H, W = int(round(H0 * args.resize)), int(round(W0 * args.resize))
    s = min(1.0, 2000.0 / max(H, W))
    sw, sh = int(round(W * s)), int(round(H * s))
    sx, sy = sw / W, sh / H
    log(f"{len(paths)} frame, {W}x{H}, deteksi di {sw}x{sh}")

    # --- mask langit
    mask_full = None
    if args.mask:
        m = cv2.imread(args.mask, cv2.IMREAD_GRAYSCALE)
        if m is None:
            raise IOError(f"tidak bisa membaca mask {args.mask}")
        mask_full = cv2.resize(m, (W, H), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
    elif args.auto_mask:
        idx = np.linspace(0, len(paths) - 1, min(5, len(paths))).astype(int)
        grays = [load_gray_small(paths[i], (sw, sh)) for i in idx]
        ms = auto_mask_small(grays)
        fg_frac = float((ms < 0.5).mean())
        if fg_frac > 0.6:
            log(f"PERINGATAN: auto-mask menandai {fg_frac:.0%} sebagai foreground, mask diabaikan")
        else:
            log(f"auto-mask: foreground {fg_frac:.0%} dari frame")
            mask_full = cv2.resize(ms, (W, H), interpolation=cv2.INTER_LINEAR)
    if mask_full is not None:
        mask_full = feather(mask_full, 3.0)
        if args.save_mask:
            cv2.imwrite(args.save_mask, (mask_full * 255).astype(np.uint8))
            log(f"mask disimpan: {args.save_mask}")
        ms_small = cv2.resize(mask_full, (sw, sh), interpolation=cv2.INTER_AREA)
        excl = cv2.dilate((ms_small < 0.5).astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    else:
        excl = None

    # --- tahap 1: bintang + transformasi (hanya data kecil di RAM)
    log("deteksi bintang...")
    smalls = []
    for p in paths:
        g = load_gray_small(p, (sw, sh))
        dog, u8 = prep(g)
        smalls.append((u8, detect_stars(dog, excl, args.max_stars)))
    ref_idx = len(paths) // 2
    if len(smalls[ref_idx][1]) < 20:
        raise RuntimeError(
            f"frame referensi cuma punya {len(smalls[ref_idx][1])} bintang terdeteksi. "
            "Frame terlalu terang/gelap atau bukan foto bintang?")
    log(f"align ke frame #{ref_idx} ({len(smalls[ref_idx][1])} bintang)...")
    trans = estimate_transforms(smalls)
    del smalls
    used = sorted(trans)
    if len(used) < 2:
        raise RuntimeError("hanya 1 frame yang berhasil di-align, stacking dibatalkan")
    for k in used:
        _, n_in, rms = trans[k]
        log(f"  frame {k}: {n_in} inlier, rms {rms:.2f}px")
    log(f"dipakai {len(used)}/{len(paths)} frame")

    # --- tahap 2: warp + akumulasi bertahap
    D = np.diag([sx, sy, 1.0])
    Dinv = np.linalg.inv(D)
    sky_sum = np.zeros((H, W, 3), np.float32)
    wsum = np.zeros((H, W), np.float32)
    ground_sum = np.zeros((H, W, 3), np.float32) if mask_full is not None else None
    ones = np.ones((H, W), np.float32)
    for i, k in enumerate(used, 1):
        img = load_bgr(paths[k])
        if img.shape[:2] != (H0, W0):
            raise ValueError(f"{os.path.basename(paths[k])}: ukuran beda dari frame pertama")
        if args.resize != 1.0:
            img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
        if ground_sum is not None:
            ground_sum += img
        if k == ref_idx:
            sky_sum += img
            wsum += 1.0
        else:
            Mf = (Dinv @ trans[k][0] @ D)[:2]
            warped = cv2.warpAffine(img, Mf, (W, H), flags=cv2.INTER_CUBIC,
                                    borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            w = cv2.warpAffine(ones, Mf, (W, H), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            sky_sum += warped * w[..., None]
            wsum += w
            del warped, w
        del img
        log(f"  stack [{i}/{len(used)}]")
    sky_sum /= np.maximum(wsum, 1e-6)[..., None]

    if mask_full is not None:
        ground_sum /= len(used)
        sky_sum -= ground_sum
        sky_sum *= mask_full[..., None]
        sky_sum += ground_sum
    return cv2.cvtColor(sky_sum, cv2.COLOR_BGR2RGB)


def main():
    ap = argparse.ArgumentParser(description="Stacker foto astro sederhana")
    ap.add_argument("frames", help="folder berisi frame (jpg/png/tif)")
    ap.add_argument("-o", "--out", required=True, help="file TIFF hasil, mis. sesi1/DSC-0042/DSC-0042.tif")
    ap.add_argument("--mode", choices=["average", "trail"], default="average")
    ap.add_argument("--mask", help="PNG mask langit (putih = langit, hitam = foreground)")
    ap.add_argument("--auto-mask", action="store_true", help="tebak foreground yang gelap (heuristik)")
    ap.add_argument("--save-mask", help="simpan mask yang dipakai ke PNG, untuk dicek")
    ap.add_argument("--resize", type=float, default=1.0, help="skala frame, mis. 0.5 untuk hemat RAM")
    ap.add_argument("--max-stars", type=int, default=600)
    ap.add_argument("--no-compress", action="store_true", help="TIFF tanpa kompresi")
    args = ap.parse_args()

    if not os.path.isdir(args.frames):
        print(f"ERROR: folder '{args.frames}' tidak ada", file=sys.stderr)
        return 2
    paths = list_frames(args.frames)
    if len(paths) < 2:
        print(f"ERROR: butuh minimal 2 frame di '{args.frames}', ketemu {len(paths)}", file=sys.stderr)
        return 2
    if not 0.05 <= args.resize <= 1.0:
        print("ERROR: --resize harus 0.05 sampai 1.0", file=sys.stderr)
        return 2
    try:
        if args.mode == "trail":
            rgb = stack_trail(paths, args.resize)
        else:
            rgb = stack_average(paths, args)
    except (IOError, ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    write_tiff(args.out, rgb, compress=not args.no_compress)
    # pratinjau 8-bit: TIFF 16-bit sering tampil rusak di galeri HP
    preview = os.path.splitext(args.out)[0] + "_preview.jpg"
    bgr8 = cv2.cvtColor((np.clip(rgb, 0, 1) * 255.0 + 0.5).astype(np.uint8), cv2.COLOR_RGB2BGR)
    cv2.imwrite(preview, bgr8, [cv2.IMWRITE_JPEG_QUALITY, 92])
    log(f"pratinjau: {preview}")
    log(f"selesai: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
