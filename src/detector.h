/* Saturated + dim cell detector from magisk/src/lhsight.c (MIT). */
static int blobs(int w, int h, int T, int mark, int nbl, u64 *sx, u64 *sy, u32 *np, int *pk) {
  u32 n = (u32)(w * h); int cw = w >> 4, ch = h >> 4, nc = cw * ch, hot = nc <= MAXCELL;
  for (int q = 0; q < nc; q++) S.cells[q] = 0;
  // fast reject: no byte > T - 1 in this word (at most 127: brighter thresholds only reject less)
  u64 add = 0x0101010101010101ull * (u64)(127 - (T - 1 > 127 ? 127 : T - 1));
  const u64 *q8 = (const u64 *)S.scratch; u32 nw = n >> 3;
  for (u32 j = 0; j < nw; j++) {
    u64 x = q8[j];
    if (!(((x + add) | x) & 0x8080808080808080ull)) continue;
    for (int bb = 0; bb < 8; bb++) {
      if ((int)((x >> (8 * bb)) & 0xFF) < T) continue;
      u32 px = (j << 3) + bb; int y = (int)(px / (u32)w), xx = (int)(px - (u32)y * (u32)w);
      if ((y >> 4) >= ch || (xx >> 4) >= cw) continue;  // the edge strip of a size that isn't a multiple of 16
      int q = (y >> 4) * cw + (xx >> 4);
      if (hot && S.hot[q]) continue;
      if (S.cells[q] < 65535) S.cells[q]++;
    }
  }
  // union 8-connected bright cells into blobs
  for (int q = 0; q < nc; q++) S.lab[q] = q;
  for (int cy = 0; cy < ch; cy++)
    for (int cx = 0; cx < cw; cx++) {
      int q = cy * cw + cx;
      if (!S.cells[q]) continue;
      if (mark && hot)
        for (int dy = -1; dy <= 1; dy++)
          for (int dx = -1; dx <= 1; dx++)
            if (cy + dy >= 0 && cy + dy < ch && cx + dx >= 0 && cx + dx < cw) S.hot[q + dy * cw + dx] = 1;
      int nb[4] = { cx > 0 ? q - 1 : -1, cy > 0 ? q - cw : -1, (cy > 0 && cx > 0) ? q - cw - 1 : -1, (cy > 0 && cx < cw - 1) ? q - cw + 1 : -1 };
      for (int e = 0; e < 4; e++) if (nb[e] >= 0 && S.cells[nb[e]]) { int r1 = find(q), r2 = find(nb[e]); if (r1 != r2) S.lab[r1] = r2; }
    }
  // per blob: centroid of pixels >= T inside its cells
  int roots[MAXB], b0 = nbl;
  for (int q = 0; q < nc; q++) {
    if (!S.cells[q]) continue;
    int r = find(q), bi = -1;
    for (int e = b0; e < nbl; e++) if (roots[e] == r) { bi = e; break; }
    if (bi < 0) { if (nbl == MAXB) continue; bi = nbl++; roots[bi] = r; sx[bi] = sy[bi] = 0; np[bi] = 0; pk[bi] = 0; }
    int x0 = (q % cw) * 16, y0 = (q / cw) * 16;
    for (int y = y0; y < y0 + 16; y++) {
      const u8 *row = S.scratch + (u32)y * (u32)w;
      for (int x = x0; x < x0 + 16; x++) {
        int v = row[x];
        if (v > pk[bi]) pk[bi] = v;
        if (v < T) continue;
        sx[bi] += (u64)(x * 10 + 5); sy[bi] += (u64)(y * 10 + 5); np[bi]++;
      }
    }
  }
  return nbl;
}
