#!/usr/bin/env python3
"""Verify IEEE-754 double precision equivalence of L3 common-denominator WENO5 JS & Mapped reciprocals."""
import random


def main():
    rng = random.Random(20261118)
    samples = [(1e-16, 1e-16, 1e-16), (1e-40, 1e-12, 1e20), (1e-20, 1.0, 1e20)]
    for _ in range(202):
        exps = [rng.uniform(-40.0, 20.0) for _ in range(3)]
        samples.append(tuple(rng.uniform(0.1, 9.9) * (10.0 ** e) + 1e-16 for e in exps))

    max_err_rec = 0.0
    max_err_map = 0.0
    for b0, b1, b2 in samples:
        # Reference separate reciprocals
        rb0, rb1, rb2 = (1.0 / b0) ** 2, (1.0 / b1) ** 2, (1.0 / b2) ** 2
        a0r, a1r, a2r = 0.1 * rb0, 0.6 * rb1, 0.3 * rb2
        sr = a0r + a1r + a2r
        w0r, w1r, w2r = a0r / sr, a1r / sr, a2r / sr

        # L3 common-denominator reciprocal (within 1e-80 .. 1e80 guard)
        if max(b0, b1, b2) < 1e80 and min(b0, b1, b2) > 1e-80:
            q0 = b0 * b1
            inv_p = 1.0 / (q0 * b2)
            ib0 = ((b1 * b2) * inv_p) ** 2
            ib1 = ((b0 * b2) * inv_p) ** 2
            ib2 = (q0 * inv_p) ** 2
        else:
            ib0, ib1, ib2 = (1.0 / b0) ** 2, (1.0 / b1) ** 2, (1.0 / b2) ** 2
        a0, a1, a2 = 0.1 * ib0, 0.6 * ib1, 0.3 * ib2
        s_inv = 1.0 / (a0 + a1 + a2)
        w0, w1, w2 = a0 * s_inv, a1 * s_inv, a2 * s_inv
        max_err_rec = max(max_err_rec, abs(w0 - w0r), abs(w1 - w1r), abs(w2 - w2r))

        # Reference Mapped WENO
        den0 = 0.01 + 0.8 * w0r
        den1 = 0.36 - 0.2 * w1r
        den2 = 0.09 + 0.4 * w2r
        am0r = w0r * (0.11 - 0.3 * w0r + w0r * w0r) / den0
        am1r = w1r * (0.96 - 1.8 * w1r + w1r * w1r) / den1
        am2r = w2r * (0.39 - 0.9 * w2r + w2r * w2r) / den2
        smr = am0r + am1r + am2r
        wm0r, wm1r, wm2r = am0r / smr, am1r / smr, am2r / smr

        # L3 common-denominator Mapped WENO
        den0c = 0.01 + 0.8 * w0
        den1c = 0.36 - 0.2 * w1
        den2c = 0.09 + 0.4 * w2
        qm = den0c * den1c
        inv_pm = 1.0 / (qm * den2c)
        am0 = w0 * (0.11 - 0.3 * w0 + w0 * w0) * (den1c * den2c * inv_pm)
        am1 = w1 * (0.96 - 1.8 * w1 + w1 * w1) * (den0c * den2c * inv_pm)
        am2 = w2 * (0.39 - 0.9 * w2 + w2 * w2) * (qm * inv_pm)
        s_invm = 1.0 / (am0 + am1 + am2)
        wm0, wm1, wm2 = am0 * s_invm, am1 * s_invm, am2 * s_invm
        max_err_map = max(max_err_map, abs(wm0 - wm0r), abs(wm1 - wm1r), abs(wm2 - wm2r))

    print(f"n_cases={len(samples)} max_err_rec={max_err_rec:.3e} max_err_map={max_err_map:.3e}")


if __name__ == "__main__":
    main()
