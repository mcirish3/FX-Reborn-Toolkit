#pragma once
#include <stdint.h>
#ifdef KERNELS_DLL
#define KAPI extern "C" __declspec(dllexport)
#elif defined(KERNELS_IMPORT)
#define KAPI extern "C" __declspec(dllimport)
#else
#define KAPI extern "C"
#endif
typedef void (*kernel_fn)(const uint8_t* a, const uint8_t* b, uint8_t* out);
struct Kernel { const char* name; kernel_fn fn; };
KAPI int get_kernels(const Kernel** list);          // AVX2/BMI2 versions (kernels.cpp, /arch:AVX2)
extern "C" int get_reference(const Kernel** list);  // scalar versions (reference.cpp, /arch:AVX)
