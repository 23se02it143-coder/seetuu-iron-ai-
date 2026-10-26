"""Render the site's imagery: dark studio shots of gym iron, lit in the IRON-AI crimson palette.

No stock photos and no network: the scenes are built from signed-distance shapes and ray-marched with numpy, then
colour-graded with a crimson gradient map so every image matches the site. Run:  python scripts/render_scenes.py

Replace any of the generated files in web/static/img/ with your own photography at any time. The page blends whatever
image is there into the background with CSS, so real photos will pick up the same look.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "web" / "static" / "img"
F = np.float32


def norm(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# ----------------------------------------------------------------- shapes
def cyl(p, axis, c, r, h, rr=0.0):
    """Rounded cylinder along `axis` (0=x,1=y,2=z), centre c, radius r, half-length h, edge rounding rr."""
    a = p[axis] - c[axis]
    u = p[(axis + 1) % 3] - c[(axis + 1) % 3]
    v = p[(axis + 2) % 3] - c[(axis + 2) % 3]
    rho = np.sqrt(u * u + v * v) - (r - rr)
    dz = np.abs(a) - (h - rr)
    return np.minimum(np.maximum(rho, dz), 0) + np.sqrt(np.maximum(rho, 0) ** 2 + np.maximum(dz, 0) ** 2) - rr


def sphere(p, c, r):
    return np.sqrt((p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2) - r


def torus_z(p, c, big, small):
    q = np.sqrt((p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2) - big
    return np.sqrt(q * q + (p[2] - c[2]) ** 2) - small


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


# ------------------------------------------------------------------ scenes
# each scene returns (d_floor, d_steel, d_rubber, d_iron); the nearest one decides the material
def scene_barbell(p):
    Y = 0.225
    steel = cyl(p, 0, (0, Y, 0), 0.0145, 1.12, 0.002)
    rub = np.full_like(p[0], 9.0)
    for s in (-1, 1):
        steel = np.minimum(steel, cyl(p, 0, (s * 0.90, Y, 0), 0.0255, 0.30, 0.004))
        for i, r in enumerate((0.225, 0.225, 0.225, 0.19)):
            x = s * (0.63 + i * 0.0245)
            rub = np.minimum(rub, cyl(p, 0, (x, Y - (0.225 - r) * 0.0, 0), r, 0.0113, 0.006))
        steel = np.minimum(steel, cyl(p, 0, (s * (0.63 + 4 * 0.0245 + 0.022), Y, 0), 0.034, 0.02, 0.006))
    return p[1], steel, rub, np.full_like(p[0], 9.0)


def scene_kettlebell(p):
    body = np.maximum(sphere(p, (0, 0.145, 0), 0.145), -(p[1] - 0.004))
    handle = torus_z(p, (0, 0.305, 0), 0.078, 0.021)
    kb = smin(body, np.maximum(handle, -(p[1] - 0.27)), 0.035)
    steel = cyl(p, 0, (0.30, 0.07, -0.02), 0.013, 0.1, 0.003)
    for s in (-1, 1):
        steel = np.minimum(steel, cyl(p, 0, (0.30 + s * 0.13, 0.07, -0.02), 0.07, 0.045, 0.01))
    rub = np.full_like(p[0], 9.0)
    for i in range(4):  # flat plates stacked at the back
        rub = np.minimum(rub, cyl(p, 1, (-0.30, 0.012 + i * 0.026, -0.22), 0.2, 0.0125, 0.006))
    return p[1], steel, rub, kb


def scene_plates(p):
    rub = np.full_like(p[0], 9.0)
    steel = np.full_like(p[0], 9.0)
    for i in range(9):  # a row of plates standing on edge, receding into the dark
        z = -i * 0.085
        r = 0.225 if i % 3 else 0.2
        rub = np.minimum(rub, cyl(p, 2, (0, r, z), r, 0.0235, 0.008))
        steel = np.minimum(steel, cyl(p, 2, (0, r, z), 0.038, 0.0255, 0.004))
    return p[1], steel, rub, np.full_like(p[0], 9.0)


# ---------------------------------------------------------------- lighting
def env(d):
    """Studio environment used for reflections: dark room, a top softbox, a crimson strip and a rim glow."""
    y = d[..., 1:2]
    top = smooth(0.35, 0.85, y) * (0.85 + 0.6 * smooth(-0.6, 0.6, d[..., 0:1]))
    col = top * np.array([1.0, 0.93, 0.9], F) * 1.9
    strip = np.exp(-(1 - np.sum(d * norm(np.array([-0.75, 0.25, 0.6], F)), -1, keepdims=True)) * 14)
    col += strip * np.array([1.0, 0.25, 0.34], F) * 2.4
    rim = np.exp(-(1 - np.sum(d * norm(np.array([0.7, 0.3, -0.75], F)), -1, keepdims=True)) * 5)
    col += rim * np.array([1.0, 0.16, 0.3], F) * 1.5
    col += 0.02 + 0.03 * smooth(-0.3, 0.6, y)
    return col.astype(F)


LIGHTS = [  # direction to light, colour, casts shadow
    (norm(np.array([0.7, 0.45, -0.7], F)), np.array([1.0, 0.17, 0.3], F) * 5.0, True),
    (norm(np.array([-0.2, 1.0, 0.35], F)), np.array([1.0, 0.92, 0.88], F) * 1.5, True),
    (norm(np.array([-0.8, 0.25, 0.5], F)), np.array([0.9, 0.2, 0.32], F) * 1.1, False),
]


def render(scene, cam_pos, target, w, h, fov=36, steps=110, tmax=9.0, focus=None, dof=1.0, seed=3, floor=True, exposure=2.4):
    t0 = time.time()
    rng = np.random.default_rng(seed)
    cam_pos, target = np.array(cam_pos, F), np.array(target, F)
    fwd = norm(target - cam_pos)
    right = norm(np.cross(fwd, np.array([0, 1, 0], F)))
    up = np.cross(right, fwd)
    aspect = w / h
    tf = np.tan(np.radians(fov) / 2)
    xs, ys = np.meshgrid(np.arange(w, dtype=F), np.arange(h, dtype=F))
    u = ((2 * (xs + 0.5) / w - 1) * aspect * tf).ravel()
    v = ((1 - 2 * (ys + 0.5) / h) * tf).ravel()
    rd = norm(fwd[None] + u[:, None] * right[None] + v[:, None] * up[None]).astype(F)
    n = w * h
    t = np.zeros(n, F)
    hit = np.zeros(n, bool)
    active = np.arange(n)

    def sdf_all(pts):
        d = scene((pts[:, 0], pts[:, 1], pts[:, 2]))
        return d if floor else (np.full_like(d[0], 9.0),) + tuple(d[1:])

    def sdf(pts):
        return np.minimum.reduce(sdf_all(pts))

    for _ in range(steps):
        if active.size == 0:
            break
        pts = cam_pos[None] + rd[active] * t[active, None]
        d = sdf(pts)
        close = d < 0.0005 + 0.0004 * t[active]
        hit[active[close]] = True
        t[active] += d * 0.92
        alive = ~close & (t[active] < tmax)
        active = active[alive]
    print(f"  marched {w}x{h} in {time.time() - t0:.0f}s, hit {hit.mean():.0%}")

    col = np.zeros((n, 3), F)
    depth = np.full(n, tmax, F)
    hi = np.where(hit)[0]
    pos = cam_pos[None] + rd[hi] * t[hi, None]
    e = 0.0012
    nx = sdf(pos + np.array([e, 0, 0], F)) - sdf(pos - np.array([e, 0, 0], F))
    ny = sdf(pos + np.array([0, e, 0], F)) - sdf(pos - np.array([0, e, 0], F))
    nz = sdf(pos + np.array([0, 0, e], F)) - sdf(pos - np.array([0, 0, e], F))
    N = norm(np.stack([nx, ny, nz], -1))
    V = -rd[hi]
    dists = np.stack(sdf_all(pos), 0)
    mat = np.argmin(dists, 0)  # 0 floor 1 steel 2 rubber 3 iron

    # ambient occlusion
    ao = np.ones(len(hi), F)
    for k, dd in enumerate((0.02, 0.05, 0.1, 0.18)):
        ao -= np.clip(dd - sdf(pos + N * dd), 0, 1) * (0.55 / (k + 1)) * 1.6
    ao = np.clip(ao, 0.15, 1)

    # albedo per material, with painted rings on the plates
    alb = np.zeros((len(hi), 3), F)
    rough = np.zeros(len(hi), F)
    rho = np.sqrt((pos[:, 1] - 0.225) ** 2 + pos[:, 2] ** 2) if scene is not scene_plates else np.sqrt(pos[:, 0] ** 2 + (pos[:, 1] - 0.213) ** 2)
    alb[mat == 0] = (0.014, 0.011, 0.013)
    alb[mat == 1] = (0.6, 0.57, 0.57)
    alb[mat == 2] = (0.06, 0.055, 0.058)
    alb[mat == 3] = (0.022, 0.02, 0.022)
    rough[mat == 0] = 0.5
    rough[mat == 1] = 0.12
    rough[mat == 2] = 0.42
    rough[mat == 3] = 0.4
    ring = (mat == 2) & (np.abs(N[:, 0]) > 0.6 if scene is scene_barbell else np.abs(N[:, 2]) > 0.6)
    band = smooth(0.205, 0.218, rho) * (1 - smooth(0.218, 0.226, rho)) + smooth(0.078, 0.086, rho) * (1 - smooth(0.086, 0.094, rho))
    alb[ring] += (band[ring, None] * np.array([0.05, 0.045, 0.048], F))
    if scene is scene_barbell:
        alb[ring] *= (0.85 + 0.3 * smooth(0.0, 0.2, rho[ring]))[:, None]

    rgb = np.zeros((len(hi), 3), F)
    ambient = np.array([0.05, 0.02, 0.03], F) * (0.55 + 0.45 * N[:, 1:2])
    rgb += alb * ambient * ao[:, None] * 5

    def shadow(o, ld, k=10.0):
        res = np.ones(len(o), F)
        tt = np.full(len(o), 0.02, F)
        for _ in range(22):
            dd = sdf(o + ld[None] * tt[:, None])
            res = np.minimum(res, np.clip(k * dd / tt, 0, 1))
            tt += np.clip(dd, 0.01, 0.25)
        return res * res * (3 - 2 * res)

    for L, lc, cast in LIGHTS:
        ndl = np.clip(N @ L, 0, 1)
        sh = shadow(pos + N * 0.004, L) if cast else np.ones(len(pos), F)
        Hh = norm(V + L[None])
        spec_pow = 2.0 / np.maximum(rough**2, 0.02) - 1.0
        spec = np.clip(np.sum(N * Hh, 1), 0, 1) ** spec_pow * (1 - rough) * 1.8
        rgb += (alb * ndl[:, None] * 1.0 + spec[:, None] * (0.25 + 0.75 * (mat == 1))[:, None]) * lc[None] * sh[:, None] * ao[:, None]

    R = rd[hi] - 2 * np.sum(rd[hi] * N, 1, keepdims=True) * N
    fres = (1 - np.clip(np.sum(N * V, 1), 0, 1)) ** 4
    f0 = np.where(mat == 1, 0.85, np.where(mat == 0, 0.05, 0.05)).astype(F)
    refl = f0 + (1 - f0) * fres
    tint = np.where((mat == 1)[:, None], np.array([1.0, 0.96, 0.95], F), np.array([1.0, 1.0, 1.0], F))
    rgb += env(R) * (refl * (1 - rough) ** 0.7 * ao)[:, None] * tint * (1.0 if scene is not scene_plates else 1.0)
    rgb += fres[:, None] * np.array([1.0, 0.16, 0.3], F) * 0.9 * (mat != 0)[:, None]

    rgb *= exposure
    if focus is None:
        focus = float(np.median(t[hi]))
    col[hi] = rgb
    depth[hi] = t[hi]
    # background: deep room with a crimson haze behind the subject
    bg = np.where(~hit)[0]
    dirs = rd[bg]
    glow = np.exp(-(1 - np.sum(dirs * norm(np.array([0.55, 0.28, -0.8], F)), 1)) * 6)[:, None] * np.array([0.5, 0.06, 0.13], F)
    col[bg] = 0.012 + glow * 0.9 + 0.01 * smooth(-0.2, 0.5, dirs[:, 1:2])
    depth[bg] = tmax

    # floor fades to black with distance and away from the pool of light
    fl = hi[mat == 0]
    px = pos[mat == 0]
    pool = np.exp(-((px[:, 0] - target[0]) ** 2 * 1.2 + (px[:, 2] - target[2]) ** 2 * 0.5))
    col[fl] = col[fl] * (0.12 + 0.88 * pool[:, None] ** 1.5)

    img = col.reshape(h, w, 3)
    dep = depth.reshape(h, w)

    # depth of field: blend sharp with two blurred copies
    if dof > 0:
        pil = Image.fromarray((np.clip(img / (1 + img), 0, 1) * 255).astype(np.uint8))
        b1 = np.asarray(pil.filter(ImageFilter.GaussianBlur(3.0 * dof * w / 1600)), F) / 255
        b2 = np.asarray(pil.filter(ImageFilter.GaussianBlur(9.0 * dof * w / 1600)), F) / 255
        base = np.asarray(pil, F) / 255
        coc = np.clip(np.abs(dep - focus) / (0.45 * focus), 0, 1)[..., None]
        mixed = np.where(coc < 0.5, base * (1 - coc * 2) + b1 * (coc * 2), b1 * (1 - (coc - 0.5) * 2) + b2 * ((coc - 0.5) * 2))
        img = mixed / np.maximum(1 - mixed, 1e-3)  # back to linear
    return post(img, rng)


def zoom_glow(bright, cx, cy, strength=0.35, n=14, spread=0.05):
    out = np.zeros_like(bright)
    h, w = bright.shape[:2]
    pil = Image.fromarray((np.clip(bright, 0, 1) * 255).astype(np.uint8))
    for i in range(1, n + 1):
        s = 1 + spread * i / n
        nw, nh = int(w * s), int(h * s)
        big = pil.resize((nw, nh), Image.BILINEAR)
        ox, oy = int((nw - w) * cx), int((nh - h) * cy)
        out += np.asarray(big.crop((ox, oy, ox + w, oy + h)), F) / 255 * (1 - i / (n + 1))
    return out / n * strength * 4


def post(img, rng, cx=0.75, cy=0.42):
    h, w = img.shape[:2]
    x = img / (1 + img * 0.55)  # filmic-ish tone curve
    x = np.clip(x, 0, 1)
    lum = x @ np.array([0.3, 0.59, 0.11], F)
    bright = np.clip(lum - 0.5, 0, 1)[..., None].repeat(3, -1)
    bloom = np.asarray(Image.fromarray((bright * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(14 * w / 1600)), F) / 255
    rays = zoom_glow(bright, cx, cy)
    x = np.clip(x + bloom * 0.9 + rays * 0.6, 0, 1)
    lum = x @ np.array([0.3, 0.59, 0.11], F)
    # crimson gradient map so every image belongs to the same family as the site
    stops = np.array([0.0, 0.16, 0.36, 0.58, 0.8, 1.0], F)
    cols = np.array([(6, 3, 5), (30, 6, 15), (77, 6, 28), (176, 52, 82), (240, 116, 138), (245, 236, 230)], F) / 255
    graded = np.stack([np.interp(lum, stops, cols[:, c]) for c in range(3)], -1)
    x = 0.8 * graded + 0.2 * x * np.array([1.0, 0.75, 0.8], F)
    # vignette + grain
    yy, xx = np.mgrid[0:h, 0:w]
    vig = 1 - 0.55 * (((xx / w - 0.5) * 1.5) ** 2 + ((yy / h - 0.5) * 1.6) ** 2)
    x *= np.clip(vig, 0.25, 1)[..., None]
    x += rng.normal(0, 0.018, (h, w, 1)).astype(F)
    return (np.clip(x, 0, 1) * 255).astype(np.uint8)


JOBS = {
    "scene-barbell": dict(scene=scene_barbell, cam=(-0.95, 0.32, 1.3), target=(0.3, 0.22, 0.0), size=(1800, 900), fov=34, dof=0.9),
    "scene-hero": dict(scene=scene_barbell, cam=(-1.0, 0.3, 1.55), target=(0.2, 0.6, 0.0), size=(2000, 1000), fov=36, dof=0.9),
    "scene-kettlebell": dict(scene=scene_kettlebell, cam=(0.15, 0.36, 1.15), target=(0.12, 0.15, 0.0), size=(1100, 1350), fov=36, dof=1.0),
    "scene-plates": dict(scene=scene_plates, cam=(-0.5, 0.3, 0.95), target=(0.0, 0.2, -0.28), size=(1800, 800), fov=36, dof=1.1),
}

if __name__ == "__main__":
    scale = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    only = sys.argv[2:] or list(JOBS)
    for name in only:
        j = JOBS[name]
        w, h = int(j["size"][0] * scale), int(j["size"][1] * scale)
        print(name)
        arr = render(j["scene"], j["cam"], j["target"], w, h, fov=j["fov"], dof=j["dof"])
        path = OUT / f"{name}.jpg"
        Image.fromarray(arr).save(path, quality=86, optimize=True, progressive=True)
        print("  saved", path.name, path.stat().st_size // 1024, "KB")
