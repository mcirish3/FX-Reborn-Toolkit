// Runs every AVX2/BMI2 kernel on random and edge-case inputs and compares with the scalar reference.
#include "kernels.h"
#include <stdio.h>
#include <string.h>
static uint64_t s = 0x9E3779B97F4A7C15ull;
static uint64_t rnd() { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return s; }
static void fill(uint8_t* p, int mode) {
  for (int i = 0; i < 32; i += 8) { uint64_t v = rnd(); memcpy(p + i, &v, 8); }
  if (mode == 1) memset(p, 0xFF, 32);
  if (mode == 2) for (int i = 0; i < 32; i += 2) { p[i] = 0x00; p[i + 1] = 0x80; }  // int16 -32768
  if (mode == 3) for (int i = 0; i < 32; ++i) p[i] &= 0x3F;                       // small counts
}
int main() {
  const Kernel *k, *r;
  int n = get_kernels(&k), m = get_reference(&r), failed = 0;
  if (n != m) { printf("table mismatch\n"); return 2; }
  for (int t = 0; t < n; ++t) {
    int bad = 0;
    for (int it = 0; it < 3000; ++it) {
      __declspec(align(32)) uint8_t a[32], b[32], o1[32], o2[32];
      fill(a, it % 4 == 1 ? 1 : it % 4 == 2 ? 2 : 0);
      fill(b, it % 3 == 0 ? 3 : it % 7 == 0 ? 2 : 0);
      memset(o1, 0xCC, 32); memset(o2, 0xCC, 32);
      k[t].fn(a, b, o1); r[t].fn(a, b, o2);
      if (memcmp(o1, o2, 32)) { if (!bad++) printf("FAIL %-10s first mismatch at iteration %d\n", k[t].name, it); }
    }
    if (bad) ++failed; else printf("ok   %s\n", k[t].name);
  }
  if (failed) printf("%d of %d kernels FAILED\n", failed, n); else printf("ALL %d KERNELS PASS\n", n);
  return failed ? 1 : 0;
}
