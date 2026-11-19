# Building ANR's nr-record for CPUs without AVX2

[nr-record](https://github.com/apex-compute/ANR#record-and-compare-frame-generation) is the frame
recorder that comes with Apex Compute's ANR frame generation. Since FG V.B19 the ANR game
packages and test kits are built for x86-64-v2 and run on CPUs without AVX2 (ANR issue #63).
The `nr-record-1.2` download is unchanged since V.B18, so it was built before that fix.

This guide builds nr-record yourself for x86-64-v2 (AMD FX, Xeon E5 v1/v2, older Intel Core),
natively on Windows. **This repository does not ship nr-record binaries.** ANR has no license
file, so its code and builds are Apex Compute's to distribute. If they publish an x86-64-v2
nr-record build, use theirs instead.

Status: builds and passes an instruction scan on an FX-8350. It hasn't been run in a game yet.

## What you need

- Windows 10/11 x64
- [Bazelisk](https://github.com/bazelbuild/bazelisk/releases) for Windows (it fetches the Bazel version the repo pins; 9.3.2 here)
- [LLVM](https://github.com/llvm/llvm-project/releases) for Windows x64 (clang-cl + lld-link; 23.1.6 was used)
- Visual Studio 2022 or 2026 with "Desktop development with C++" (MSVC + Windows SDK)
- Git

## Steps

1. Clone ANR into a folder **with no spaces in the path**. Don't use a junction or symlink:
   Bazel then reports "absolute path inclusion" errors.

   ```
   git clone https://github.com/apex-compute/ANR C:\src\ANR
   cd /d C:\src\ANR
   ```

   (Tested at commit `57a139a`.)

2. Point Bazel at LLVM and MSVC (adjust the paths to your installs):

   ```
   set BAZEL_LLVM=C:\LLVM
   set BAZEL_VC=C:\Program Files\Microsoft Visual Studio\18\Community\VC
   ```

3. Create `.bazelrc.user` in the repo root with:

   ```
   build:windows --copt=-march=x86-64-v2 --host_copt=-march=x86-64-v2
   ```

4. Apply the Windows DXC patch below. Upstream compiles the D3D12 shader kernels with the
   Linux build of Microsoft's DXC. The patch uses the Windows build from the same DXC release.

   ```
   git apply local-windows-dxc.patch
   ```

5. Build. ANR's README builds the Windows parts with `--config=windows_cross` on Linux; natively
   on Windows use `--config=windows`:

   ```
   bazel build --config=windows //record:nr-record //record/replay:nr-video //record/capture:package //record/replay:nr-replay
   ```

   Lay the outputs out like the official `nr-record-*-windows.zip` (`install.cmd`, `capture\`, `tools\`).
   If the target names have changed, check ANR's README ("Build:").

## local-windows-dxc.patch

```diff
diff --git a/MODULE.bazel b/MODULE.bazel
--- a/MODULE.bazel
+++ b/MODULE.bazel
@@ -96,6 +96,14 @@ http_archive(
     urls = ["https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2609/linux_dxc_2026_09_28.x86_x64.tar.gz"],
 )
 
+# LOCAL PATCH: Microsoft's Windows DXC from the same release, for a native Windows build of the D3D12 kernels.
+http_archive(
+    name = "dxc_windows",
+    build_file_content = 'filegroup(name = "files", srcs = glob(["bin/x64/**", "inc/**"]), visibility = ["//visibility:public"])',
+    sha256 = "ad31b1fc8443175d204f77a611fdb3ef2ec42759bdc2f1167368de24a4a7e7f1",
+    urls = ["https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2609/dxc_2026_09_29.zip"],
+)
+
 # The Shader Model 6.10 preview DXC (slang.bzl's slang_dxil_linalg; fetched only if a target uses it).
 http_archive(
     name = "dxc_preview_linux",
diff --git a/tools/slang.bzl b/tools/slang.bzl
--- a/tools/slang.bzl
+++ b/tools/slang.bzl
@@ -29,7 +29,7 @@ def _slang_shaders_impl(ctx):
     tools = ctx.files._slang_files
     dxc = None
     if target == "dxil":
-        dxc = [f for f in ctx.files.dxc if f.basename == "dxc"]
+        dxc = [f for f in ctx.files.dxc if f.basename in ("dxc", "dxc.exe")]
         if not dxc:
             fail("DXIL needs dxc = \"//third_party:dxcompiler\" (slang_dxil sets it)")
         dxc = dxc[0]
@@ -145,8 +145,8 @@ def slang_dxil_d3d12(**kwargs):
     """DXIL for D3D12, built on Linux by Microsoft's DXC release (the version slang_dxil builds from source)."""
     slang_shaders(
         target = "dxil",
-        dxc = "@dxc_linux//:files",
-        exec_compatible_with = ["@platforms//os:linux"],
+        dxc = "@dxc_windows//:files",  # LOCAL PATCH: native Windows build
+        exec_compatible_with = ["@platforms//os:windows"],
         **kwargs
     )
```

## Checking the result

Run the toolkit's scan on each built `.exe`/`.dll` (`fxkit.py scan <file>`). Expect:

- **AVX2 hits:** inside CPU-checked code (the C++ runtime picks an AVX2 path only when the CPU has it).
  The x86-64-v2 build showed 32–113 per file, all in such code.
- **2 BMI2 (`shlx`) hits in nr-video.exe:** these are in the MSVC CRT's FMA3 `pow()`. A test
  program using the same CRT code ran fine on an FX-8350, so the CRT doesn't take that path there.

`dlss\amd\nr_record_ffx_dx12.dll` is AMD's prebuilt FidelityFX DLL from the ANR package. It isn't
rebuilt.
