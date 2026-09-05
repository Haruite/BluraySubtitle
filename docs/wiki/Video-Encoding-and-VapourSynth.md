# Video Encoding and VapourSynth

English | [简体中文](Video-Encoding-and-VapourSynth.zh-Hans.md)

This page covers encoder settings and the VPy processing path. For container, codec, remux, and encode terminology, see [Media Fundamentals](Media-Fundamentals.md). Final encoded output is muxed into MKV.

## Choosing H.264, H.265, or AV1

| Encoder | Supported output depth | Practical tradeoff |
| --- | --- | --- |
| x264 / AVC | 8-bit default; 10-bit sets `--profile high10` | Mature, generally faster, and broadly compatible with older players; usually needs more data than a well-configured newer codec |
| x265 / HEVC | 8/10/12-bit; 10-bit default | Project default; better compression efficiency at greater encoding cost. Dolby Vision preservation requires 10/12-bit. |
| SVT-AV1 | 8/10-bit for normal output | Modern compression and film-grain tools; check decoder support. The current workflow omits Dolby Vision with a task message. |

Ten-bit SDR output can reduce quantization/banding problems but does not turn SDR into HDR. Codec background belongs in [Media Formats](Media-Formats-and-Dolby-Vision.md#video-formats).

SVT-AV1 12-bit is experimental and unusable in the current setup-script build: its patch bypasses upstream's 8/10-bit restriction and adds Professional-profile signaling, but does not implement valid 12-bit encoding; real tests produce a grey picture. Valid 12-bit support requires maintaining the upstream source, not merely selecting the option.

Quality depends on source texture/motion, encoder version, rate control, preset, filters, and playback conditions. Compare representative samples from the same source at the intended viewing distance; transcoding one test result into another codec adds generation loss and biases the comparison.

## The BluraySubtitle encode pipeline

For Blu-ray input, the high-level path is:

```text
selected MPLS and tracks
        │
        ▼
staging MKV with the authored playlist/chapter range
        │
        ▼
VapourSynth .vpy script
        │
        ▼
vspipe --y4m
        │
        ├── x264  → .h264
        ├── x265  → .hevc
        └── SVT-AV1 → .ivf
        │
        ▼
final MKV with selected audio, subtitles, chapters, attachments, and metadata
```

The staging remux preserves source audio. Audio conversion and final audio cleanup happen only in the final mux after video encoding succeeds. This avoids performing a lossy or expensive audio operation before the video result exists.

`vspipe` supplies Y4M frames to the encoder through a pipe, so a normal encode does not need a full uncompressed intermediate video file. The encoder's elementary-stream result is temporary; the user-facing result is the final MKV.

## Rate control and the meaning of presets

### CRF

The built-in presets use **CRF** (Constant Rate Factor) rate control. CRF asks the encoder to pursue a quality level rather than a fixed final size:

- a lower CRF generally means higher quality and a larger file;
- a higher CRF generally means more loss and a smaller file; and
- the result size still varies with source complexity.

CRF numbers are not equivalent between x264, x265, and SVT-AV1. A value of 18 in one encoder must not be treated as the same quality as 18 in another.

For a strict delivery size, bitrate-based one-pass or multi-pass workflows may be more appropriate, but BluraySubtitle's built-in presets are CRF-oriented. User-defined presets and direct parameter edits can use other modes when the selected encoder supports them.

### Encoder preset

An encoder's own `--preset` controls the speed/compression-efficiency tradeoff. A slower preset spends more CPU time searching coding choices and can usually store a chosen quality more efficiently. It is not a simple quality switch: using a slower preset with the same CRF does not guarantee the same size or a uniformly visible improvement.

BluraySubtitle adds a second, project-level preset layer:

| Project preset | Intended use |
| --- | --- |
| Fast | Quick output or test encodes |
| Balanced | Default starting point |
| High Quality | More quality and analysis work |
| Extreme | Very slow, large-quality-budget starting point |

The four built-in presets are read-only. Advanced settings can add, rename, edit, and delete user-defined presets for the encoder currently selected there; only those user-defined entries are stored in `config.json`. The Encode page shows the built-in and user-defined presets for its current encoder. Selecting a preset fills the parameter field, while directly editing that field keeps the selected preset name unchanged. The visible parameter string at task launch is authoritative.

## Built-in parameter presets

The Encode page shows the authoritative current parameter string. Built-in values are defined in [`src/core/encode_presets.py`](../../src/core/encode_presets.py) and are not duplicated here because they may change. They are starting points rather than promises of a particular size or visual quality. In particular, x265's `placebo` preset has sharply diminishing returns, while a higher numeric SVT-AV1 preset means a faster encode with a compression-efficiency tradeoff.

## Common parameters in plain language

| Parameter | Practical meaning |
| --- | --- |
| `--crf` | Quality/size target for CRF rate control |
| `--preset` | Encoder effort versus speed |
| `--aq-mode`, `--aq-strength` | Redistribute quantization according to spatial/visual complexity |
| `--bframes` | Maximum use of bidirectionally predicted frames |
| `--ref` | Reference-frame budget |
| `--me`, `--subme`, `--merange` | Motion-search method, refinement, and range |
| `--keyint` | Maximum keyframe/GOP interval |
| `--rc-lookahead` | Frames inspected ahead for rate-control and frame-type decisions |
| `--psy-rd`, `--psy-rdoq` | Psychovisual weighting in mode and quantization decisions |
| `--deblock` | In-loop deblocking behavior |
| `--film-grain` in SVT-AV1 | Film-grain synthesis strength, not a generic denoiser |

Parameters interact. Copying a long command from a different source type can make the result worse or only make the encode slower. Always keep the final color range, primaries, transfer, matrix, bit depth, and chroma format consistent with the processed frames.

## What VapourSynth does

VapourSynth is a Python-driven frame server. A `.vpy` script:

1. opens and indexes the source;
2. constructs a graph of frame-processing filters;
3. exposes one or more output `VideoNode` objects with `set_output()`; and
4. produces requested frames on demand when `vspipe` or a preview application evaluates that graph.

It does not encode video by itself. In this project, `vspipe` evaluates the selected output and writes Y4M frames to x264, x265, or SVT-AV1.

The GUI can generate, edit, and preview a `.vpy` script. Before encoding it injects the actual source path and, when enabled, native-resolution information. The selected output bit depth is synchronized with the final `fmtc.bitdepth(..., bits=N)` conversion. Hardsub mode activates the `assrender.TextSub` line and supplies the selected ASS, SSA, or SRT subtitle path. SUP hardsubs are not supported by this text-rendering path.

### Previewing processed and source frames in VSEdit

The generated default VPy exposes the processed `res` as output index `0` and the original `src8` as output index `1`. Click **Preview script**, then choose **Script > Preview** in VSEdit or press `F5` to open the preview window. Keep the same frame selected and press `0` for the processed frame or `1` for the source frame; the preview window title confirms the active index. Press `S` in the preview window to run **Save snapshot** for the displayed frame. These default keys can be reviewed or changed under **Settings > Hotkeys** in VSEdit.

Use sufficient intermediate precision and dither when reducing bit depth. Verify output `0`, frame count/rate, scan type, color properties, crop dimensions, and representative motion/gradients before a full encode. The [short-test instructions](../../README.md#how-do-i-run-a-short-encode-test) explain when a VPy-only trim is sufficient and when the whole media timeline must be cut.

### Automatic getnative

BluraySubtitle's getnative implementation is adapted from [Infiziert90/getnative](https://github.com/Infiziert90/getnative). It estimates the vertical resolution at which a source was rendered before mastering and the scaling kernel most likely used to enlarge it. When automatic getnative is enabled for a source no taller than 1080p, the result becomes the generated VPy's native height and inverse-scaling kernel. This can remove the master's upscale before subsequent filtering or resizing, but it neither changes the source file nor restores detail that was never present.

Before sample extraction, Encode probes the actual video stream dimensions. A source taller than 1080p skips automatic getnative immediately even if the option is selected; this avoids adding a potentially very long high-resolution analysis to the normal encode workflow. Higher-resolution analysis remains available through `src/scripts/getnative_file.py`. Write the returned `height` and `kernel` into the VPy as `native_h` and `native_kernel` before encoding.

#### Frame selection and scheduling

FFmpeg extracts candidate frames in incremental rounds instead of preparing 100 images in advance. Frames are ranked by edge energy, luminance variance, and entropy so that detailed, high-contrast pictures are tried first. A round can launch at most 20 samples, further limited by the logical CPU count and currently available physical memory. The memory calculation reserves 2 GiB for the system and budgets 800 MiB for every sample process. The 800 MiB value is a scheduling estimate, not a hard process limit: a complex frame or a short-lived final scan may use more.

Every sample already launched is allowed to finish, and every kernel and sample result is printed as soon as it becomes available. Five valid curves are only the threshold for deciding whether another round is necessary; all valid results from the completed round still participate in the final decision. If fewer than five are found, extraction continues incrementally, up to a 100-sample safety ceiling. A final result still requires at least two usable curves.

#### What one sample analyzes

The installed system Python coordinates extraction, processes, and final ranking. The portable Python 3.13 VapourSynth environment runs `getnative.vpy`, which converts the PNG sample from RGB to BT.709 grayscale and evaluates all 16 inverse-scaling candidates: bilinear; eight bicubic parameter sets; Lanczos with 2, 3, 4, and 5 taps; and Spline16, Spline36, and Spline64. Each candidate descales the frame to a trial height, scales it back to the source dimensions, and measures the reconstruction error. The vertical search range is normally 40% through 98% of the source height.

For speed, every kernel first receives a centered half-size, step-4 coarse scan and then a full-frame 1p scan around the best coarse height. The first three priority kernels always reach the fine scan. After that, a kernel whose like-for-like coarse score is below 45% of the best coarse score may skip its fine scan, while still reporting the coarse result. After all kernels have reported, the winning kernel is checked again with a full-frame step-4 pass followed by a full-frame ±20p, 1p scan. This avoids retaining a second full-range 1p graph.
Each VSPipe process uses one VapourSynth frame worker and a 256 MiB frame-cache ceiling to control concurrent memory growth.

#### Curve and multi-frame selection

For each reconstruction-error curve, getnative looks for the sharp adjacent-height error drop described by the upstream method. The candidate height is the current height at that drop, and its primary score is the previous height's error divided by the current height's error. The metric's five-pixel border crop only excludes unreliable edge pixels; it is not a five-pixel correction to the detected height. Broad valleys are used only as a fallback when no credible sharp drop exists.

Unstable or oscillating tails are rejected before ranking. The 535p-through-545p false-positive band remains fixed because genuinely 540p material is uncommon. It is not scaled to 1070p through 1090p for a 2160p source: 1080p-to-2160p upscales are common, and no equivalent UHD interference band has been confirmed. The stable-curve upper limit is `source height × 1040 / 1080`; curve-tail spans and the high-resolution oscillation boundary use the same source-height scale. A 1080p source therefore rejects values above 1040p, while a 2160p source rejects values above 2080p and keeps 1080p-area candidates eligible.

Usable samples are grouped by rounded height. Each sample is weighted as `min(score, 2) * (height / search-range maximum)^4`; the three strongest weights in a height group determine which group wins, with the higher height breaking an exact tie. This preserves the empirically useful preference for a high resolution with a strong score without requiring dense consensus, since some titles yield very few usable frames. The selected group's weighted height and kernel votes produce the final VPy values.

Getnative is a heuristic: detailed line art usually gives clearer curves than dark scenes, credits, soft photography, noise, or mixed-resolution material. Compare per-kernel output across representative episodes. For a standalone test, set `video_file` in `src/scripts/getnative_file.py`; the higher-resolution VPy setup is described above.

### Generated VPy restoration controls

The five Encode controls replace `denoise_strength`, `dehalo_strength`, `dering_strength`, `deband_strength`, and `antialiasing_strength` in the generated VPy at launch. A custom script without these names is unchanged. Startup defaults are saved under **Advanced**.

| Control | Range / default | Use and processing |
| --- | --- | --- |
| Denoise | `0.0`–`3.0` / `0.6` | Conservative spatial luma `nlm_ispc.NLMeans` (`d=0`, small search), protected by a Prewitt mask and `mvsfunc.LimitFilter`. Reduce strength if grain/paper texture changes; inspect the removed noise before increasing it. |
| Dehalo | `0.0`–`1.0` / `0.0` | Enable for broad sharpening halos. A luma downscale/upscale estimate based on [abcxyz](https://github.com/xyx98/my-vapoursynth-script) is constrained by `rgvs.Repair` and blended by strength. |
| Dering | `0.0`–`1.0` / `0.0` | Enable for narrow DCT/rescale ringing. A `MinBlur`/`HQDering`-style mask excludes the edge itself and blends repaired, limited smoothing around it. |
| Deband | `0.0`–`1.0` / `0.5` | YUV `placebo.Deband`, with a softened multi-plane Prewitt mask restoring edges/texture; reduce or disable when gradients/effects are harmed. |
| Anti-aliasing | `0.0`–`1.0` / `0.5` | Limited EEDI2 luma blended toward the debanded source; disable for detailed or intentionally pixel-sharp material without aliasing. |

`0` disables a stage. Deband/anti-aliasing use a literal half blend at `0.5` and full limited output at `1`. Other restoration stages affect luma only. For dehalo/dering, start at `0.15`–`0.25`; use `0.25`–`0.35` only for clear defects after frame checks, and avoid more than `0.4` across a whole title. Their strength controls blending, not mask width or halo radius.

Identify the defect before enabling dehalo or dering together. Grain, paper texture, rain, glow, line art, and high-resolution artwork can resemble defects; inspect bright, dark, textured, and effects-heavy scenes. Use a custom VPy for shot-specific tuning of radius, masks, thresholds, or other internal parameters.

### Comparison images and full-frame corruption checks

**Output comparison images** writes one source/encoded PNG pair under `<actual output folder>/Compare`, using the same zero-based frame number. It scans the encoded frame count, scans the source only to that count, then decodes the matching frame on both sides. It does not rely on timestamp-only matching or replace the Encode button's stage label.

**Check corrupted frames** reruns the exact encoding VPy and compares every output frame with the final MKV using FFmpeg PSNR, also checking frame counts and decoder errors. `<actual output folder>/FrameCheck/<name>.frame-check.json` records `pass`, `suspect` (low PSNR), `fail` (count/decode error), or `error` (checker failure). Non-pass results retain the MKV and add a row warning; visual review remains necessary.

Both stages report frames, speed, percentage, and ETA every 15 seconds. The frame-check switch is on Encode; its luma/chroma thresholds are under **Settings > Advanced > Default encode settings**. `encode.frame_check_luma_psnr_threshold_db` and `encode.frame_check_chroma_psnr_threshold_db` accept `0.0`–`100.0` and default to `30.0`; U/V share the chroma value. Any applicable plane below its threshold makes a frame suspicious. Higher thresholds increase sensitivity and false positives.

Measured examples from one machine illustrate the added cost:

| Sample | Comparison images | Full frame check |
| --- | --- | --- |
| 52-second 1080p | 36 seconds (0.7× duration) | 127 seconds (2.4×) |
| 34-second cropped 4K Dolby Vision | 80 seconds (2.4×) | 248 seconds (7.3×) |

Decoder, filters, resolution, storage, and runtime versions affect these timings. A full check renders every VPy frame and can take substantially longer than the video itself.

### Automatic black-border cropping

Automatic black-border cropping is opt-in. Before preparing the final VPy, BluraySubtitle probes duration and dimensions, then uses FFmpeg input-side seeks to analyze one pseudo-random point in each time bucket. It samples one point per 150 seconds, bounded to 4–24 points, and decodes only three nearby frames at each point without writing image files. The fixed crop is derived from the union of all detected active rectangles, so a pixel used by any sampled frame is kept. The managed `src8.std.Crop(...)` operation is inserted before the rest of the filter graph.
Automatic analysis is necessarily heuristic: dark scenes, credits, overlays, and unusual borders can produce a wrong result, so inspect the reported margins and encoded picture.

The crop is even-aligned. Existing managed blocks are replaced or removed between rows. A custom VPy must expose a safe `src8`/`res` insertion boundary; an unknown boundary or a non-managed `Crop`/`CropAbs` call combined with nonzero automatic cropping fails the row to prevent ambiguous or double cropping.

### Automatic HDR metadata handling

For Dolby Vision MKV input, the workflow extracts HEVC and prepares task-owned base-layer and RPU files before encoding. Missing or invalid required intermediates fail the row rather than silently dropping Dolby Vision.

Before starting the encoder, BluraySubtitle samples output 0's first, middle, and last frames. Stable `_ColorRange`, `_Primaries`, `_Transfer`, `_Matrix`, and `_ChromaLocation` properties take precedence over source metadata; missing properties fall back to the source. The row stops if the sampled values differ.

When the actual source exposes HDR10+, x265 10/12-bit encoding extracts its validated JSON and checks the metadata frame count and source frame rate against the VPy timeline. The actual x265 executable is probed once per binary identity: when it advertises `--dhdr10-info`, the metadata is supplied during encoding; otherwise, or when native verification fails, `hdr10plus_tool` performs verified post-injection. Failures continue without dynamic metadata and retain non-empty JSON for diagnosis. Custom scripts using this path must preserve frame order.

Dolby Vision uses native x265 RPU input when the executable advertises it and the row already has VBV and mastering-display parameters. Otherwise, or when native verification fails, it uses `dovi_tool` injection without changing rate control.

When both HDR10+ and Dolby Vision are present, x265 writes both in one encode if both native paths qualify. HEVC is checked for both metadata sets after the last injection and before final muxing.

If automatic cropping changes the coded dimensions, each Dolby Vision L5 active-area preset is adjusted by the physical crop before the resulting profile 8.1 RPU is supplied to either native x265 or post-injection. A manually supplied RPU is therefore incompatible with automatic cropping. HDR10+ does not have a corresponding crop-offset edit in this workflow: its source brightness statistics are retained without remeasurement after cropping or an additional crop-specific prompt.

After the final MKV is published, BluraySubtitle re-probes the static fields it added automatically and reruns the active dynamic-metadata checks. Dolby Vision must report profile 8 with the same RPU frame count as the VPy output. A mismatch retains the MKV, records a non-overwriting warning report, and lets later rows continue.

## Interlaced, telecined, and mixed-cadence sources

The generated VPy cannot safely choose one automatic treatment for every source. `_FieldBased` can report whether a frame is progressive (`0`), bottom-field-first (`1`), or top-field-first (`2`), but it does not say why the fields exist. True interlaced camera or video material needs deinterlacing; 3:2 telecined film or animation normally needs field matching plus decimation (IVTC); mixed progressive, telecined, and interlaced sections may need range-specific handling.
Blindly using QTGMC can create an unnecessary doubled frame rate or preserve telecine judder, while blindly applying IVTC can discard real motion fields. Container metadata can also be wrong, so confirm the field order and cadence by frame-stepping representative motion, pans, and credits instead of trusting one metadata label.

Create a row-specific custom VPy and replace the progressive-only guard immediately after `LWLibavSource`. For genuinely interlaced material, a typical QTGMC starting point is:

```python
import havsfunc as haf

# TFF=True for top-field-first; use False for bottom-field-first.
# FPSDivisor=1 preserves both temporal field samples as double-rate progressive video.
src8 = haf.QTGMC(src8, TFF=True, Preset="Slower", FPSDivisor=1)
src8 = src8.std.SetFrameProps(_FieldBased=0)
```

Use `FPSDivisor=2` only when a single-rate progressive result is intentional and its motion has been checked. For regular 3:2 telecine, install a field-matching plugin such as VIVTC and start from its field match and decimation path instead:

```python
matched = core.vivtc.VFM(src8, order=1)  # order=1 TFF; order=0 BFF
src8 = core.vivtc.VDecimate(matched)
src8 = src8.std.SetFrameProps(_FieldBased=0)
```

Do not merely clear `_FieldBased`; that changes metadata without reconstructing a progressive picture. Put deinterlacing or IVTC before bit-depth conversion, getnative/descale, denoising, and other restoration. For mixed cadence, split or conditionally replace the affected ranges rather than forcing one filter over the whole title. Preview combing, motion cadence, fades, and scrolling credits, then verify the resulting frame rate, duration, and audio synchronization before a full encode.
QTGMC/VIVTC and their dependencies must be present in the VapourSynth runtime used for the encode; custom scripts own those additional dependencies.

## Plugins used by the generated script

The default script is a usable starting point, not a universal restoration recipe. It accepts progressive video only and rejects field-based input instead of processing it incorrectly. L-SMASH indexes are stored under the system temporary directory rather than beside a potentially read-only disc source. When native inverse scaling is active, only luma uses the detected descale kernel; chroma follows Blu-ray's left chroma location, and a reconstruction mask restores the original YUV planes over credits and other final-resolution composites. Its current plugin chain includes:

Credits, on-picture text, and already-burned subtitles are not recognized by OCR or by their meaning. When native inverse scaling is active, the script compares the original 16-bit luma with luma that was descaled to the detected native height and then reconstructed to the output size. It binarizes absolute differences above two 8-bit code values (scaled to 16-bit), expands the mask twice, and inflates it once. After filtering and resizing, white mask regions receive the original YUV planes.
Text composited at the final master resolution normally differs strongly from the native-height reconstruction, which is why Staff rolls and burned subtitles are usually protected. Fine texture, sharpening, line art, or noise can also trigger the same mask; this is an intentional source-preserving false positive, not semantic text detection. Optional external ASS/SSA/SRT hardsubs are separate and are rendered directly by `assrender.TextSub` from the selected subtitle file.

| Namespace/package | Role in the generated script |
| --- | --- |
| `lsmas.LWLibavSource` | Indexed source reader |
| `fmtc` | Bit-depth conversion and resampling |
| `descale` | Optional inverse scaling from detected native resolution |
| `nlm_ispc` | Denoising |
| `placebo` | Debanding on every supported platform |
| `mvsfunc.LimitFilter` | Limit filtered changes against reference clips |
| `eedi2` | Edge-directed antialiasing |
| `rgvs.Repair` | Constrain repaired planes |
| built-in `std` and `resize` | Plane operations, format-safe resizing, output construction |
| `assrender.TextSub` | Optional ASS/SSA/SRT rendering for hardsubs |

Availability is environment-dependent. A script fails at evaluation time if a required plugin or Python module is missing; the setup scripts and External Tools settings determine which runtime is used.

## Other commonly encountered VapourSynth plugins

Custom scripts often use a different chain. Common categories include:

| Task | Common examples | Main caution |
| --- | --- | --- |
| Source loading | BestSource, L-SMASH-Works, FFMS2 | Indexing and timestamp behavior differ |
| Deinterlacing/IVTC | QTGMC, VIVTC, TIVTC | Determine field order and cadence first |
| Rescaling/descaling | `resize`, fmtconv, descale, zimg-based helpers | Preserve range, matrix, chroma location, and aspect ratio |
| Denoising | BM3D variants, DFTTest, KNLMeansCL/NLMeans, MVTools-based filters | Excessive denoising destroys texture and grain |
| Debanding | neo_f3kdb, libplacebo | Add controlled grain/dither to avoid re-quantized bands |
| Antialiasing | EEDI2/EEDI3, NNEDI3/ZNEDI3, sangnom-based helpers | Mask changes when only line art needs correction |
| Subtitle rendering | assrender/libass-based filters | Fonts and script resolution affect layout |

These names describe ecosystem options, not guaranteed BluraySubtitle dependencies. A custom script owns its plugin requirements and output correctness.

## Further reading

See [References](References.md) for the H.264, H.265, AV1, x265, SVT-AV1, and VapourSynth specifications and manuals.
