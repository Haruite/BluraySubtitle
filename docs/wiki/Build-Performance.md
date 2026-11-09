# Build Performance

English | [简体中文](Build-Performance.zh-Hans.md)

## Windows setup script

All three runs used commit `c83b40c0238dfed5ddf50e830a2de1b3239bf757` (`fix(setup): fall back when GitHub release API fails`) as their source base. The baseline used the pre-optimization working tree snapshot, and the optimized cold and warm runs used the optimized snapshot. Both snapshots included changes that were uncommitted at the time.

The November 9, 2026 measurements used an x64 Windows 11 VM with an Intel Core i5-13600KF, 20 logical processors, 24 GiB of memory, Visual Studio Enterprise 2026, CMake 4.4.5, and Ninja 1.13.2. Each column reports one run of the setup script in `-Mode Build`, timed from process launch through temporary-file cleanup.

The baseline and optimized cold run started with empty build and pip caches and retained the MSYS2 download cache. The baseline started with Python 3.12.10 preinstalled, and the builds used Python 3.15.2. The warm run cleared the installed project tools and the VapourSynth Python loader while retaining Python, the installed MSYS2 dependencies, and the build cache. The nine build cache archives occupied about 274 MiB.

### Elapsed time

| Component | Baseline | Optimized cold setup | Warm restoration |
| --- | ---: | ---: | ---: |
| Python selection, installation, and dependencies | 2m 12s | 1m 55s | 16s |
| MSYS2 and build packages | 49s | 49s | 26s |
| Preinstalled tool checks and other tool installations | 43s | 31s | 29s |
| x264 | 3m 10s | 3m 01s | 3.4s |
| x265 | 10m 36s | 3m 51s | 1.3s |
| SVT-AV1 | 1m 47s | 1m 23s | 1.6s |
| FDK-AAC and fdkaac | 4m 24s | 1m 32s | 1.7s |
| libass | 23s | 19s | 1.4s |
| VapourSynth Classic and Python binding | 1m 54s | 1m 47s | 6.0s |
| VapourSynth plugins and VSEdit | 4m 39s | 4m 04s | 6.3s |
| Other initialization and cleanup | 10s | 9.6s | 5.2s |
| **Total** | **30m 47s** | **19m 22s** | **1m 37s** |

The optimized cold run took 37.1% less time than the baseline. Within the VapourSynth plugin stage, FFTW configuration, compilation, and installation took 98.5 seconds in the baseline and 89.6 seconds in the optimized cold run.

### CPU utilization

Total VM CPU utilization was sampled about every 11 seconds. The table reports the median and highest observed sample, with sample counts in parentheses.

| Stage | Baseline | Optimized cold run |
| --- | ---: | ---: |
| Full run | 6% / 100% (162) | 7% / 100% (101) |
| x264 | 6% / 85% (17) | 4% / 77% (16) |
| x265 | 6% / 100% (56) | 11% / 100% (21) |
| x265 12-bit core compilation | 5% / 12% (19) | 12% / 98% (7) |
| SVT-AV1 | 7% / 100% (9) | 13% / 100% (7) |
| FDK-AAC and fdkaac | 7% / 68% (23) | 10.5% / 95% (8) |
| libass | 5% / 7% (2) | 3.5% / 5% (2) |
| VapourSynth Classic and Python binding | 16% / 83% (10) | 28.5% / 82% (8) |
| VapourSynth plugins and VSEdit | 8% / 98% (25) | 6.5% / 100% (22) |
| FFTW configuration, compilation, and installation | 60% / 84% (9) | 56% / 98% (8) |

The warm run recorded a median of 2.5% and a highest sample of 7% across 8 samples.

The x265 12-bit static library took 221 seconds to compile with the Visual Studio generator. A separate run using the same MSVC toolchain and Ninja took 74.7 seconds and recorded up to 14 concurrent NASM processes. The Ninja run used a fresh build directory and a previously read source tree.

### Memory usage

The same resource samples recorded the VM's available memory. Estimated memory in use is the VM's 24 GiB of total memory minus the available memory in each sample.

| Run | Median estimated usage | Highest sampled estimate | Samples |
| --- | ---: | ---: | ---: |
| Baseline | 6.62 GiB | 10.35 GiB | 162 |
| Optimized cold run | 6.75 GiB | 10.08 GiB | 101 |
| Warm restoration | 6.77 GiB | 7.02 GiB | 8 |

## Docker image build

The November 9, 2026 measurements used commit `c83b40c0238dfed5ddf50e830a2de1b3239bf757` as the source base. The Dockerfile came from that commit, and the application source snapshot included uncommitted changes. The `linux/amd64` image used Ubuntu 26.04 and built on an x86-64 Ubuntu 26.04.1 host with an Intel Core i5-13600KF, 20 logical processors, 125.60 GiB of OS-visible memory, Docker Engine 29.1.3, and BuildKit 0.26.2.

Both runs used host networking, set `APT_MIRROR` to `http://mirrors.tuna.tsinghua.edu.cn/ubuntu/`, and loaded the image into the Docker Engine image store. The cold run used `--no-cache` with the base image and Dockerfile frontend already downloaded. The immediate rebuild reused the same source snapshot and parameters with caching enabled. BuildKit reported 52 cached instructions after the base image.

### Elapsed time

| Measurement | Cold build | Cached rebuild |
| --- | ---: | ---: |
| **Total wall time** | **14m 08.35s** | **5.82s** |
| Image export and unpacking | 68.4s | 0.2s |

The major cold-build stages use the layer durations reported by BuildKit. Durations for multiple layers of the same component are combined.

| Stage | Cold build |
| --- | ---: |
| APT initialization and system dependency installation | 148.2s |
| FFmpeg, mpv, libass, and libplacebo | 128.1s |
| x265 source download and build | 148.2s |
| SVT-AV1 | 43.1s |
| FDK-AAC and fdkaac | 36.7s |
| FLAC | 1.3s |
| VapourSynth Classic and Python binding | 31.6s |
| VSEdit | 23.5s |
| VapourSynth plugins | 129.4s |
| Python runtime packages | 28.8s |
| x264 | 18.2s |

In the system dependency layer, APT reported transferring 536 MB of packages in 17 seconds. Docker reported an image size of 1.41 GiB.

### CPU and memory usage

Host CPU utilization and memory were sampled about once per second. Estimated memory in use is `MemTotal` minus `MemAvailable`. Peaks are the highest recorded samples.

| Run | Samples | CPU median | CPU peak | Memory median | Memory peak |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cold build | 848 | 7.0% | 100.0% | 8.71 GiB | 14.04 GiB |
| Cached rebuild | 6 | 5.6% | 12.7% | 8.93 GiB | 8.97 GiB |

## Linux setup script on WSL 2

The November 9, 2026 measurements used `setup_linux_environment.sh` from commit `c83b40c0238dfed5ddf50e830a2de1b3239bf757`. Ubuntu 26.04.1 LTS and Ubuntu 22.04.5 LTS ran on the same x86-64 WSL 2 host with an Intel Core i5-13600KF, 20 logical processors, 62.79 GiB of WSL-visible memory, and kernel `6.18.54.1-microsoft-standard-WSL2`.

Before the first run on each distribution, Ubuntu's APT sources used the Tsinghua University mirror over HTTPS and `apt update` and `apt upgrade` had completed. The runs used non-interactive WSL root sessions and ran one at a time. Ubuntu 26.04 mounted `/tmp` as tmpfs. Ubuntu 22.04 used ext4 for `/tmp`, and both used ext4 for `/var/tmp`.

The first 22.04 run exited with code `1` while configuring libplacebo for mpv. The root session had installed Meson 1.12.1 in its Python user site. With `PYTHONNOUSERSITE=1`, the build used the distro's Meson 0.61.2, and libplacebo required at least 1.3.0. Meson 1.12.1 was then installed system-wide with the user site disabled. The retry reused the installed system dependencies, Shaderc, MKVToolNix, VapourSynth, libdovi, and dav1d. The 26.04 first run and 22.04 retry both passed setup verification and exited with code `0`.

### Linux setup elapsed time

Each total covers one script invocation from launch to exit. Stage times are approximate and use timestamped log boundaries. A dash marks a skipped or unreached stage.

| Stage (seconds) | Ubuntu 26.04 first run | Ubuntu 22.04 first attempt | Ubuntu 22.04 retry |
| --- | ---: | ---: | ---: |
| APT checks, system dependencies, and font cache | 46.8 | 42.0 | 0.7 (reused) |
| Shaderc source build | — | 77.7 | — |
| MKVToolNix | 17.2 | 174.9 | 1.1 (reused) |
| VapourSynth Classic and Python binding | 63.7 | 80.4 | 4.1 (reused) |
| FFmpeg, mpv, and their build dependencies | 201.4 | 256.0 (failed) | 150.8 |
| x264 | 22.5 | — | 34.0 |
| x265 | 174.1 | — | 128.2 |
| SVT-AV1 | 57.6 | — | 95.6 |
| tsMuxer, dovi_tool, and hdr10plus_tool | 15.0 | — | 14.3 |
| FDK-AAC and fdkaac | 33.5 | — | 33.4 |
| FLAC, descale, 7-Zip, and bundled scripts | 19.6 | — | 46.7 |
| VSEdit | 41.5 | — | 31.2 |
| L-SMASH and core VapourSynth plugins | 220.5 | — | 252.0 |
| Desktop VapourSynth plugins | 43.3 | — | 40.2 |
| Desktop configuration, Python dependencies, and verification | 35.8 | — | 38.2 |
| **Total elapsed** | **16m 32.70s** | **10m 31.03s** | **14m 30.56s** |

APT reported downloading 200 MB in 9 seconds for the initial system dependencies on 26.04 and 179 MB in 7 seconds on 22.04. The 26.04 run installed MKVToolNix 103.0 from the upstream APT repository. On 22.04, setup built MKVToolNix 98.0 for Qt 6.2 compatibility, with 124.0 seconds spent in the Rake build. The first 22.04 attempt also spent 146.0 seconds setting up Rust and cargo-c and building and installing libdovi within the FFmpeg/mpv stage.

### WSL 2 CPU and memory usage

CPU utilization across the 20 logical processors and memory use were sampled about once per second inside WSL 2. Estimated memory in use is `MemTotal` minus `MemAvailable`. Peaks are the highest recorded samples.

| Run | Samples | CPU median | CPU peak | Memory median | Memory peak |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ubuntu 26.04 first run | 990 | 3.44% | 100.00% | 1.950 GiB | 6.711 GiB |
| Ubuntu 22.04 first attempt | 630 | 5.05% | 100.00% | 2.496 GiB | 12.101 GiB |
| Ubuntu 22.04 retry | 869 | 3.49% | 100.00% | 1.775 GiB | 5.732 GiB |
