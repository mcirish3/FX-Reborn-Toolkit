// Compiled with /arch:AVX2. Every kernel uses AVX2 or BMI2 instructions.
#include "kernels.h"
#include <immintrin.h>
#include <string.h>
#define L(p) _mm256_loadu_si256((const __m256i*)(p))
#define S(p, v) _mm256_storeu_si256((__m256i*)(p), v)
#define K(name) static __declspec(noinline) void name(const uint8_t* a, const uint8_t* b, uint8_t* o)
static int table[64] = {0};
K(add32) { S(o, _mm256_add_epi32(L(a), L(b))); }
K(mullo32) { S(o, _mm256_mullo_epi32(L(a), L(b))); }
K(sllv32) { S(o, _mm256_sllv_epi32(L(a), _mm256_and_si256(L(b), _mm256_set1_epi32(63)))); }
K(srav32) { S(o, _mm256_srav_epi32(L(a), _mm256_and_si256(L(b), _mm256_set1_epi32(63)))); }
K(srlv64) { S(o, _mm256_srlv_epi64(L(a), _mm256_and_si256(L(b), _mm256_set1_epi64x(127)))); }
K(permd) { S(o, _mm256_permutevar8x32_epi32(L(a), L(b))); }
K(pshufb) { S(o, _mm256_shuffle_epi8(L(a), L(b))); }
K(sad) { S(o, _mm256_sad_epu8(L(a), L(b))); }
K(cmpgt32) { S(o, _mm256_cmpgt_epi32(L(a), L(b))); }
K(maxu8) { S(o, _mm256_max_epu8(L(a), L(b))); }
K(abs16) { S(o, _mm256_abs_epi16(L(a))); }
K(madd16) { S(o, _mm256_madd_epi16(L(a), L(b))); }
K(packs32) { S(o, _mm256_packs_epi32(L(a), L(b))); }
K(unpacklo8) { S(o, _mm256_unpacklo_epi8(L(a), L(b))); }
K(permq) { S(o, _mm256_permute4x64_epi64(L(a), 0x1B)); }
K(blend32) { S(o, _mm256_blend_epi32(L(a), L(b), 0xA5)); }
K(hadd32) { S(o, _mm256_hadd_epi32(L(a), L(b))); }
K(avgu8) { S(o, _mm256_avg_epu8(L(a), L(b))); }
K(zx8to32) { S(o, _mm256_cvtepu8_epi32(_mm_loadl_epi64((const __m128i*)a))); }
K(bcastd) { S(o, _mm256_broadcastd_epi32(_mm_loadu_si128((const __m128i*)a))); }
K(gather) { for (int i = 0; i < 64; ++i) table[i] = (int)(i * 2654435761u); S(o, _mm256_i32gather_epi32(table, _mm256_and_si256(L(b), _mm256_set1_epi32(63)), 4)); }
K(movemask) { int m = _mm256_movemask_epi8(L(a)); memset(o, 0, 32); memcpy(o, &m, 4); }
K(swap128) { __m256i v = L(a); S(o, _mm256_inserti128_si256(_mm256_castsi128_si256(_mm256_extracti128_si256(v, 1)), _mm256_castsi256_si128(v), 1)); }
K(srldq) { S(o, _mm256_srli_si256(L(a), 3)); }
K(muleu32) { S(o, _mm256_mul_epu32(L(a), L(b))); }
K(mulhi16) { S(o, _mm256_mulhi_epi16(L(a), L(b))); }
K(subsu8) { S(o, _mm256_subs_epu8(L(a), L(b))); }
K(xor256) { S(o, _mm256_xor_si256(L(a), L(b))); }
K(sra16) { S(o, _mm256_srai_epi16(L(a), 5)); }
// BMI2 (scalar)
#define U32(p, i) (((const uint32_t*)(p))[i])
#define U64(p, i) (((const uint64_t*)(p))[i])
static void clr(uint8_t* o) { memset(o, 0, 32); }
K(shlx) { clr(o); ((uint32_t*)o)[0] = _shlx_u32(U32(a, 0), U32(b, 0)); }
K(shrx64) { clr(o); ((uint64_t*)o)[0] = _shrx_u64(U64(a, 0), (unsigned)U64(b, 0)); }
K(sarx) { clr(o); ((int32_t*)o)[0] = _sarx_i32((int32_t)U32(a, 0), U32(b, 0)); }
K(rorx) { clr(o); ((uint32_t*)o)[0] = _rorx_u32(U32(a, 0), 13); }
K(bzhi) { clr(o); ((uint32_t*)o)[0] = _bzhi_u32(U32(a, 0), U32(b, 0) & 63); }
K(pdep) { clr(o); ((uint32_t*)o)[0] = _pdep_u32(U32(a, 0), U32(b, 0)); }
K(pext) { clr(o); ((uint32_t*)o)[0] = _pext_u32(U32(a, 0), U32(b, 0)); }
K(mulx) { clr(o); unsigned long long hi; ((uint64_t*)o)[0] = _mulx_u64(U64(a, 0), U64(b, 0), &hi); ((uint64_t*)o)[1] = hi; }
static const Kernel kernels[] = {
  {"add32", add32}, {"mullo32", mullo32}, {"sllv32", sllv32}, {"srav32", srav32}, {"srlv64", srlv64},
  {"permd", permd}, {"pshufb", pshufb}, {"sad", sad}, {"cmpgt32", cmpgt32}, {"maxu8", maxu8},
  {"abs16", abs16}, {"madd16", madd16}, {"packs32", packs32}, {"unpacklo8", unpacklo8}, {"permq", permq},
  {"blend32", blend32}, {"hadd32", hadd32}, {"avgu8", avgu8}, {"zx8to32", zx8to32}, {"bcastd", bcastd},
  {"gather", gather}, {"movemask", movemask}, {"swap128", swap128}, {"srldq", srldq}, {"muleu32", muleu32},
  {"mulhi16", mulhi16}, {"subsu8", subsu8}, {"xor256", xor256}, {"sra16", sra16},
  {"shlx", shlx}, {"shrx64", shrx64}, {"sarx", sarx}, {"rorx", rorx}, {"bzhi", bzhi}, {"pdep", pdep},
  {"pext", pext}, {"mulx", mulx}};
KAPI int get_kernels(const Kernel** list) { *list = kernels; return sizeof(kernels) / sizeof(kernels[0]); }
