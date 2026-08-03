# Video Encoding and VapourSynth

[简体中文](Video-Encoding-and-VapourSynth.zh-Hans.md)

Encoding is the stage that turns decoded video frames into a new compressed video stream. It is different from remuxing: a remux copies an existing coded stream, while an encode decodes frames, optionally processes them, and makes new codec decisions. This page describes the codecs, encoders, presets, and VapourSynth path used by BluraySubtitle.

See [Media Fundamentals](Media-Fundamentals.md#media-as-layers) for the distinction between codecs, encoder implementations, and containers. This page focuses on choosing and configuring the video encoder; BluraySubtitle places its final encoded stream in MKV.

## Choosing H.264, H.265, or AV1

### H.264 / AVC with x264

H.264 is the oldest of the three choices and has the broadest hardware and software playback compatibility. x264 is mature, predictable, and usually faster than the newer-codec alternatives at practical settings. It is a useful choice for older players, low-powered clients, or workflows where compatibility matters more than the smallest possible file.

x264 supports only 8-bit and 10-bit output. BluraySubtitle uses 8-bit by default; selecting 10-bit switches the x264 profile to `--profile high10`. H.264 usually needs more data than a carefully configured newer codec for a comparable result, but codec generation alone never determines quality.

### H.265 / HEVC with x265

H.265 succeeds H.264 and adds more flexible block partitioning, prediction, and coding tools. x265 can normally achieve better compression efficiency than x264, especially for high-resolution material, at the cost of more encoding work and somewhat narrower compatibility.

x265 is the project's default encoder, with 10-bit output as the default depth. Ten-bit encoding is also useful for SDR sources because the finer internal and output precision can reduce quantization and banding problems; it does not turn SDR into HDR. BluraySubtitle supports 8-, 10-, and 12-bit x265 output.

The project's encoded Dolby Vision preservation path requires x265 with 10- or 12-bit output. That is a project implementation constraint, not a general claim that every x265 encode preserves every Dolby Vision profile.

### AV1 with SVT-AV1

AV1 is an open video coding standard developed by the Alliance for Open Media. It targets high compression efficiency and includes tools such as film-grain synthesis. SVT-AV1 is the standalone AV1 encoder integrated by this project.

AV1 can be attractive when file size and modern playback environments matter, but encoding cost and device support must be checked against the intended audience. Use 8- or 10-bit SVT-AV1 for normal output. BluraySubtitle writes an IVF intermediate before final MKV muxing.

SvtAv1EncApp's 12-bit path is experimental and is not a usable encode path in the current project. Upstream SvtAv1EncApp accepts only 8- and 10-bit encoder depths and rejects 12-bit encoding. The Windows setup script applies a source patch that bypasses that restriction and writes the required Professional-profile signaling, but the patch does not implement the missing 12-bit encoder behavior. Real encode tests produce an unusable grey picture.
Users who need 12-bit SVT-AV1 must modify and maintain the upstream source themselves so that it produces valid 12-bit output; selecting 12-bit with the executable built by the setup script is not sufficient.

The current project does not retain Dolby Vision metadata when encoding with SVT-AV1. Choose x265 10/12-bit if the documented Dolby Vision encode path is required.

### There is no universal quality ranking

“AV1 is better than H.265, which is better than H.264” is too simple for an actual encode. Results depend on:

- source resolution, grain, animation style, motion, and existing artifacts;
- encoder implementation and version;
- rate-control target;
- preset and individual analysis parameters;
- filtering before encoding; and
- the playback device and decoder.

Compare short representative samples at the intended viewing distance. Do not compare codecs by re-encoding one already compressed result into another codec, because the later encode also receives the earlier encode's losses.

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

## Comparison images and full-frame corruption checks

**Output comparison images** writes one source/encoded PNG pair under `<actual output folder>/Compare`. Both images use the same zero-based video frame number. BluraySubtitle first determines the exact frame counts shared by the VPy reference and completed video, then decodes both sides to the selected frame; timestamp-only matching is not used. On the tested machine, this stage took about 36 seconds for a 52-second 1080p sample and about 80 seconds for a 34-second cropped 4K Dolby Vision sample, approximately 0.7 and 2.4 times the respective video durations. Treat these measurements as scale examples rather than promises: source decoding, VPy filters, resolution, storage, and runtime versions can change the ratio.

**Check corrupted frames** is a separate full check after the final MKV exists. It reruns the exact VPy used for encoding, decodes the completed video, compares every corresponding frame with FFmpeg PSNR, verifies the frame counts, and records decoder errors. Reports are written to `<actual output folder>/FrameCheck/<name>.frame-check.json`; statuses are `pass`, `suspect` for low-PSNR frames, `fail` for count mismatches or decode errors, and `error` when the checker itself cannot complete. A non-pass result retains the completed MKV and adds a row warning. This check does not replace visual review and cannot classify every possible content defect.

The enable checkbox remains on the Encode page. Its luma and chroma PSNR thresholds are shown under **Settings > Advanced > Default encode settings**, not on the Encode page. They are stored as `encode.frame_check_luma_psnr_threshold_db` and `encode.frame_check_chroma_psnr_threshold_db`, accept `0.0` through `100.0`, and default to `30.0` and `40.0`, respectively; U and V share the chroma value. A frame is suspicious when any applicable plane is below its threshold. Raising either value increases that plane's sensitivity and false positives; lowering it ignores progressively larger differences.

The full check is usually slower than comparison-image output because it renders every VPy frame. The same test run took about 127 seconds for the 52-second 1080p sample and 248 seconds for the 34-second cropped 4K sample, approximately 2.4 and 7.3 times their video durations. Heavy filters and full-length 4K sources can therefore add minutes or substantially longer.

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

The GUI can generate, edit, and preview a `.vpy` script. Before encoding it injects the actual source path and, when enabled, native-resolution information. The selected output bit depth is synchronized with the final `fmtc.bitdepth(..., bits=N)` conversion. Hardsub mode activates the `assrender.TextSub` line and supplies the selected subtitle path.

### Automatic getnative

BluraySubtitle's automatic getnative is adapted from [Infiziert90/getnative](https://github.com/Infiziert90/getnative). It estimates the vertical resolution at which a 1080p source was rendered before mastering and the scaling kernel most likely used to enlarge it. When automatic getnative is enabled, the result becomes the generated VPy's native height and inverse-scaling kernel. This can remove the master's upscale before subsequent filtering or resizing, but it neither changes the source file nor restores detail that was never present.

#### Frame selection and scheduling

FFmpeg extracts candidate frames in incremental rounds instead of preparing 100 images in advance. Frames are ranked by edge energy, luminance variance, and entropy so that detailed, high-contrast pictures are tried first. A round can launch at most 20 samples, further limited by the logical CPU count and currently available physical memory. The memory calculation reserves 2 GiB for the system and budgets 800 MiB for every sample process. The 800 MiB value is a scheduling estimate, not a hard process limit: a complex frame or a short-lived final scan may use more.

Every sample already launched is allowed to finish, and every kernel and sample result is printed as soon as it becomes available. Five valid curves are only the threshold for deciding whether another round is necessary; all valid results from the completed round still participate in the final decision. If fewer than five are found, extraction continues incrementally, up to a 100-sample safety ceiling. A final result still requires at least two usable curves.

#### What one sample analyzes

The installed system Python coordinates extraction, processes, and final ranking. The portable Python 3.13 VapourSynth environment runs `getnative.vpy`, which converts the PNG sample from RGB to BT.709 grayscale and evaluates all 16 inverse-scaling candidates: bilinear; eight bicubic parameter sets; Lanczos with 2, 3, 4, and 5 taps; and Spline16, Spline36, and Spline64. Each candidate descales the frame to a trial height, scales it back to the source dimensions, and measures the reconstruction error. The vertical search range is normally 40% through 98% of the source height.

For speed, every kernel first receives a centered half-size, step-4 coarse scan and then a full-frame 1p scan around the best coarse height. The first three priority kernels always reach the fine scan. After that, a kernel whose like-for-like coarse score is below 45% of the best coarse score may skip its fine scan, while still reporting the coarse result. After all kernels have reported, the winning kernel is checked again with a full-frame step-4 pass followed by a full-frame ±20p, 1p scan. This avoids retaining a second full-range 1p graph.
Each VSPipe process uses one VapourSynth frame worker and a 256 MiB frame-cache ceiling to control concurrent memory growth.

#### Curve and multi-frame selection

For each reconstruction-error curve, getnative looks for the sharp adjacent-height error drop described by the upstream method. The candidate height is the current height at that drop, and its primary score is the previous height's error divided by the current height's error. The metric's five-pixel border crop only excludes unreliable edge pixels; it is not a five-pixel correction to the detected height. Broad valleys are used only as a fallback when no credible sharp drop exists.

Unstable or oscillating tails are rejected before ranking. Heights from 535p through 545p are deliberately excluded because this band produces pervasive false positives in practical material, and candidates above 1040p are removed as implausible curve-tail results. Consequently, genuinely native 540p material cannot be detected automatically and must be configured manually.

Usable samples are grouped by rounded height. Each sample is weighted as `min(score, 2) * (height / search-range maximum)^4`; the three strongest weights in a height group determine which group wins, with the higher height breaking an exact tie. This preserves the empirically useful preference for a high resolution with a strong score without requiring dense consensus, since some titles yield very few usable frames. The selected group's weighted height and kernel votes produce the final VPy values.

Automatic getnative remains a heuristic and can consume substantial time and memory. Clean line art with visible detail usually gives the clearest curves; dark scenes, credits, soft photography, noise, mixed animation pipelines, and later resizes may not. Review the per-kernel output and compare several episodes when results vary. To test one file outside the GUI, edit `video_file` in `src/scripts/getnative_file.py` and run that script.

### Generated VPy restoration controls

The Encode page exposes five numeric strengths immediately below the getnative, automatic-crop, and comparison-image options. Their values are captured when the task starts and replace the generated script's top-level `denoise_strength`, `dehalo_strength`, `dering_strength`, `deband_strength`, and `antialiasing_strength` assignments. A custom VPy that does not define those names is left unchanged. The same startup defaults can be saved under **Advanced** settings.

| Control | Range / default | Recommended use | Generated-script behavior |
| --- | --- | --- | --- |
| Denoise | `0.0`–`3.0` / `0.6` | Keep `0.6` as a conservative starting point; reduce it when intentional grain or paper texture changes, and raise it only after inspecting the extracted noise layer. | `nlm_ispc.NLMeans` processes luma only, spatially (`d=0`), with a small search. A Prewitt mask restores strong edges and `mvsfunc.LimitFilter` caps every remaining change. This replaces the old fixed `h=3` reference that could erase grain and texture before later filters. |
| Dehalo | `0.0`–`1.0` / `0.0` | Leave it at `0` unless a sharpening halo is visible. Start at `0.15`–`0.25`; values around `0.25`–`0.35` are for clear halos after representative-frame checks. Avoid more than `0.4` for a full title unless the affected shots are isolated and inspected. | A conservative luma-only variant of the `abcxyz` idea from [xyx98/my-vapoursynth-script](https://github.com/xyx98/my-vapoursynth-script) builds a broad downscale/upscale halo estimate, constrains it with `rgvs.Repair`, and blends only the requested fraction. Strength is a blend amount, not the halo radius. |
| Dering | `0.0`–`1.0` / `0.0` | Leave it at `0` without visible ringing. Start at `0.15`–`0.25`; `0.25`–`0.35` is reserved for clear DCT/rescale ringing. Avoid more than `0.4` as a title-wide setting because line art and fine texture can soften. | A `MinBlur`/`HQDering`-style path builds a narrow band around strong edges, excludes the edge itself, and applies repaired, tightly limited smoothing only through that mask. Strength blends the masked result; it does not widen the ring mask. |
| Deband | `0.0`–`1.0` / `0.5` | Keep the moderate `0.5` starting point for ordinary animation; use `0` when no banding is present or delicate gradients/effects are harmed, and approach `1` only after checking flat gradients. | A limited `placebo.Deband` candidate processes YUV. A softened multi-plane Prewitt mask restores edges and texture before blending: `0` skips the stage, `0.5` applies half of the adaptively protected result, and `1` applies it fully. |
| Anti-aliasing | `0.0`–`1.0` / `0.5` | Keep the moderate `0.5` starting point when aliasing is plausible. Use `0` for high-detail or intentionally pixel-sharp material without visible aliasing, and approach `1` only after checking line sharpness. | The repaired EEDI2 result is limited toward the debanded source luma. `0` skips it, intermediate values blend it with the debanded luma, and `1` applies the full limited result. |

Every stage can be disabled independently with `0`. Denoise, dehalo, dering, and anti-aliasing affect luma only; deband processes YUV. Deband and anti-aliasing start at the literal blend midpoint `0.5`, while defect-specific dehalo and dering remain off. Grain, paper texture, rain, intentional glow, thin line art, and high-resolution artwork can all resemble defects, so inspect representative bright, dark, textured, and effects-heavy frames before committing to a full encode.
Do not enable dehalo and dering together merely because both controls are available: first identify whether the visible artifact is a broad sharpening halo, a narrow ringing band, or intentional artwork.

The high-level blend controls are the useful generic boundary. Internal parameters such as halo radius, ring-mask width, placebo threshold/radius, EEDI2 thresholds, and reconstruction-mask threshold interact with source scale and defect shape, so they remain script details rather than additional GUI settings. Use a custom VPy when those internals require shot-specific tuning.

Automatic black-border cropping is opt-in. Before preparing the final VPy, BluraySubtitle probes duration and dimensions, then uses FFmpeg input-side seeks to analyze one pseudo-random point in each time bucket. It samples one point per 150 seconds, bounded to 4–24 points, and decodes only three nearby frames at each point without writing image files. The fixed crop is derived from the union of all detected active rectangles, so a pixel used by any sampled frame is kept. The managed `src8.std.Crop(...)` operation is inserted before the rest of the filter graph.
Automatic analysis is necessarily heuristic: dark scenes, credits, overlays, and unusual borders can produce a wrong result, so inspect the reported margins and encoded picture.

Before starting the encoder, BluraySubtitle samples output 0's first, middle, and last frames. Stable `_ColorRange`, `_Primaries`, `_Transfer`, `_Matrix`, and `_ChromaLocation` properties take precedence over source metadata; missing properties fall back to the source. The row stops if the sampled values differ.

When the actual source exposes HDR10+, x265 10/12-bit encoding extracts its validated JSON and checks the metadata frame count and source frame rate against the VPy timeline. The actual x265 executable is probed once per binary identity: when it advertises `--dhdr10-info`, the metadata is supplied during encoding; otherwise, or when native verification fails, `hdr10plus_tool` performs verified post-injection. Failures continue without dynamic metadata and retain non-empty JSON for diagnosis. Custom scripts using this path must preserve frame order.

For combined HDR10+ and Dolby Vision output, x265 writes both in the same encode when its actual executable advertises both native paths and the row already has VBV and mastering-display parameters. Missing or unverified native support uses the existing injection tools without changing rate control. The HEVC is checked for both metadata sets after the last injection and before final muxing.

If automatic cropping changes the coded dimensions, each Dolby Vision L5 active-area preset is adjusted by the physical crop before the resulting profile 8.1 RPU is supplied to either native x265 or post-injection. A manually supplied RPU is therefore incompatible with automatic cropping. HDR10+ does not have a corresponding crop-offset edit in this workflow: its source metadata is retained without an additional crop-specific prompt.

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
Text composited at the final master resolution normally differs strongly from the native-height reconstruction, which is why Staff rolls and burned subtitles are usually protected. Fine texture, sharpening, line art, or noise can also trigger the same mask; this is an intentional source-preserving false positive, not semantic text detection. Optional external ASS/SSA hardsubs are separate and are rendered directly by `assrender.TextSub` from the selected subtitle file.

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
| `assrender.TextSub` | Optional ASS/SSA rendering for hardsubs |

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

## Script-design checklist

- Verify source frame count, frame rate, scan type, and field order.
- Preserve or deliberately set `_Matrix`, `_Transfer`, `_Primaries`, `_ColorRange`, and chroma-location properties.
- Perform destructive filtering only after comparing representative frames.
- Use sufficient intermediate precision, then dither when reducing bit depth.
- Keep crop and resize dimensions valid for the output chroma subsampling.
- Preview dark gradients, grain, line art, motion, and credits rather than only clean static scenes.
- Make exactly the intended clip the primary `set_output()` result.
- Run a short encode with the final encoder parameters before starting the full title.

## Further reading

See [References](References.md) for the H.264, H.265, AV1, x265, SVT-AV1, and VapourSynth specifications and manuals.
