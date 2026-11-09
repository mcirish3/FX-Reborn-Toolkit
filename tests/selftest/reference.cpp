// Plain C reference for every kernel, compiled WITHOUT AVX2 (/arch:AVX).
#include "kernels.h"
#include <string.h>
#include <intrin.h>
#define I16(p) ((const int16_t*)(p))
#define I32(p) ((const int32_t*)(p))
#define U32(p) ((const uint32_t*)(p))
#define U64(p) ((const uint64_t*)(p))
#define O16 ((int16_t*)o)
#define O32 ((int32_t*)o)
#define OU32 ((uint32_t*)o)
#define OU64 ((uint64_t*)o)
#define K(name) static __declspec(noinline) void name(const uint8_t* a, const uint8_t* b, uint8_t* o)
static int16_t sat16(int32_t v) { return v > 32767 ? 32767 : v < -32768 ? -32768 : (int16_t)v; }
K(add32) { for (int i = 0; i < 8; ++i) OU32[i] = U32(a)[i] + U32(b)[i]; }
K(mullo32) { for (int i = 0; i < 8; ++i) OU32[i] = U32(a)[i] * U32(b)[i]; }
K(sllv32) { for (int i = 0; i < 8; ++i) { uint32_t c = U32(b)[i] & 63; OU32[i] = c > 31 ? 0 : U32(a)[i] << c; } }
K(srav32) { for (int i = 0; i < 8; ++i) { uint32_t c = U32(b)[i] & 63; O32[i] = I32(a)[i] >> (c > 31 ? 31 : c); } }
K(srlv64) { for (int i = 0; i < 4; ++i) { uint64_t c = U64(b)[i] & 127; OU64[i] = c > 63 ? 0 : U64(a)[i] >> c; } }
K(permd) { for (int i = 0; i < 8; ++i) OU32[i] = U32(a)[U32(b)[i] & 7]; }
K(pshufb) { for (int i = 0; i < 32; ++i) { int L = i / 16; o[i] = (b[i] & 0x80) ? 0 : a[L * 16 + (b[i] & 15)]; } }
K(sad) { memset(o, 0, 32); for (int j = 0; j < 4; ++j) { int s = 0; for (int k = 0; k < 8; ++k) { int d = a[j * 8 + k] - b[j * 8 + k]; s += d < 0 ? -d : d; } OU64[j] = (uint64_t)s; } }
K(cmpgt32) { for (int i = 0; i < 8; ++i) O32[i] = I32(a)[i] > I32(b)[i] ? -1 : 0; }
K(maxu8) { for (int i = 0; i < 32; ++i) o[i] = a[i] > b[i] ? a[i] : b[i]; }
K(abs16) { for (int i = 0; i < 16; ++i) { int16_t v = I16(a)[i]; O16[i] = (int16_t)(v < 0 ? (uint16_t)(0u - (uint32_t)(int32_t)v) : v); } }
K(madd16) { for (int i = 0; i < 8; ++i) { int64_t s = (int64_t)I16(a)[2 * i] * I16(b)[2 * i] + (int64_t)I16(a)[2 * i + 1] * I16(b)[2 * i + 1]; O32[i] = (int32_t)(uint32_t)s; } }
K(packs32) { for (int L = 0; L < 2; ++L) for (int k = 0; k < 4; ++k) { O16[L * 8 + k] = sat16(I32(a)[L * 4 + k]); O16[L * 8 + 4 + k] = sat16(I32(b)[L * 4 + k]); } }
K(unpacklo8) { for (int L = 0; L < 2; ++L) for (int k = 0; k < 8; ++k) { o[L * 16 + 2 * k] = a[L * 16 + k]; o[L * 16 + 2 * k + 1] = b[L * 16 + k]; } }
K(permq) { for (int i = 0; i < 4; ++i) OU64[i] = U64(a)[(0x1B >> (2 * i)) & 3]; }
K(blend32) { for (int i = 0; i < 8; ++i) OU32[i] = ((0xA5 >> i) & 1) ? U32(b)[i] : U32(a)[i]; }
K(hadd32) { for (int L = 0; L < 2; ++L) { const uint32_t* x = U32(a) + L * 4; const uint32_t* y = U32(b) + L * 4; OU32[L * 4] = x[0] + x[1]; OU32[L * 4 + 1] = x[2] + x[3]; OU32[L * 4 + 2] = y[0] + y[1]; OU32[L * 4 + 3] = y[2] + y[3]; } }
K(avgu8) { for (int i = 0; i < 32; ++i) o[i] = (uint8_t)((a[i] + b[i] + 1) >> 1); }
K(zx8to32) { for (int i = 0; i < 8; ++i) OU32[i] = a[i]; }
K(bcastd) { for (int i = 0; i < 8; ++i) OU32[i] = U32(a)[0]; }
K(gather) { for (int i = 0; i < 8; ++i) OU32[i] = (uint32_t)((U32(b)[i] & 63) * 2654435761u); }
K(movemask) { uint32_t m = 0; for (int i = 0; i < 32; ++i) m |= (uint32_t)(a[i] >> 7) << i; memset(o, 0, 32); memcpy(o, &m, 4); }
K(swap128) { memcpy(o, a + 16, 16); memcpy(o + 16, a, 16); }
K(srldq) { for (int L = 0; L < 2; ++L) for (int k = 0; k < 16; ++k) o[L * 16 + k] = k + 3 < 16 ? a[L * 16 + k + 3] : 0; }
K(muleu32) { for (int i = 0; i < 4; ++i) OU64[i] = (uint64_t)U32(a)[2 * i] * U32(b)[2 * i]; }
K(mulhi16) { for (int i = 0; i < 16; ++i) O16[i] = (int16_t)(((int32_t)I16(a)[i] * I16(b)[i]) >> 16); }
K(subsu8) { for (int i = 0; i < 32; ++i) o[i] = a[i] > b[i] ? (uint8_t)(a[i] - b[i]) : 0; }
K(xor256) { for (int i = 0; i < 32; ++i) o[i] = a[i] ^ b[i]; }
K(sra16) { for (int i = 0; i < 16; ++i) O16[i] = (int16_t)(I16(a)[i] >> 5); }
static void clr(uint8_t* o) { memset(o, 0, 32); }
K(shlx) { clr(o); OU32[0] = U32(a)[0] << (U32(b)[0] & 31); }
K(shrx64) { clr(o); OU64[0] = U64(a)[0] >> (U64(b)[0] & 63); }
K(sarx) { clr(o); O32[0] = I32(a)[0] >> (U32(b)[0] & 31); }
K(rorx) { clr(o); uint32_t x = U32(a)[0]; OU32[0] = (x >> 13) | (x << 19); }
K(bzhi) { clr(o); uint32_t n = U32(b)[0] & 63; OU32[0] = n >= 32 ? U32(a)[0] : U32(a)[0] & ((1u << n) - 1); }
K(pdep) { clr(o); uint32_t src = U32(a)[0], mask = U32(b)[0], r = 0; for (uint32_t bit = 1; mask; bit <<= 1) { uint32_t low = mask & (0u - mask); if (src & bit) r |= low; mask &= mask - 1; } OU32[0] = r; }
K(pext) { clr(o); uint32_t src = U32(a)[0], mask = U32(b)[0], r = 0; for (uint32_t bit = 1; mask; bit <<= 1) { uint32_t low = mask & (0u - mask); if (src & low) r |= bit; mask &= mask - 1; } OU32[0] = r; }
K(mulx) { clr(o); uint64_t hi; OU64[0] = _umul128(U64(a)[0], U64(b)[0], &hi); OU64[1] = hi; }
static const Kernel ref[] = {
  {"add32", add32}, {"mullo32", mullo32}, {"sllv32", sllv32}, {"srav32", srav32}, {"srlv64", srlv64},
  {"permd", permd}, {"pshufb", pshufb}, {"sad", sad}, {"cmpgt32", cmpgt32}, {"maxu8", maxu8},
  {"abs16", abs16}, {"madd16", madd16}, {"packs32", packs32}, {"unpacklo8", unpacklo8}, {"permq", permq},
  {"blend32", blend32}, {"hadd32", hadd32}, {"avgu8", avgu8}, {"zx8to32", zx8to32}, {"bcastd", bcastd},
  {"gather", gather}, {"movemask", movemask}, {"swap128", swap128}, {"srldq", srldq}, {"muleu32", muleu32},
  {"mulhi16", mulhi16}, {"subsu8", subsu8}, {"xor256", xor256}, {"sra16", sra16},
  {"shlx", shlx}, {"shrx64", shrx64}, {"sarx", sarx}, {"rorx", rorx}, {"bzhi", bzhi}, {"pdep", pdep},
  {"pext", pext}, {"mulx", mulx}};
extern "C" int get_reference(const Kernel** list) { *list = ref; return sizeof(ref) / sizeof(ref[0]); }
