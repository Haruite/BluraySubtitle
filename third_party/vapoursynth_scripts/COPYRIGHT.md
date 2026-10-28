# VapourSynth Python Filter Scripts: Copyright and Provenance

English | [简体中文](COPYRIGHT.zh-Hans.md)

These third-party scripts remain the work of their upstream authors and contributors. BluraySubtitle's root MIT license does not replace their licenses or grant rights that their upstreams have not granted. Credits and source references embedded in individual functions also apply.

## Imported snapshot

The snapshot was imported on 2026-10-28 from the `VapourSynthScripts` files distributed in [AmusementClub/tools 2025H1p](https://github.com/AmusementClub/tools/releases/tag/2025H1p), asset `vapoursynth_portable_25H1.1p_cpu.7z`. The distribution is the provenance of these copies, not a shared license for all scripts. Setup and packaging read the checked-in files; they do not download that archive for Python scripts.

The import adds a provenance comment, normalizes line endings to CRLF, and removes trailing whitespace. In particular, the MIR-modified `havsfunc.py` is identified by its header as `33-7f0a9a7-AC-4`, based on commit `7f0a9a7a37b60a05b9f408024d203e511e544a61`. The distribution's changelog identifies the `muvsfunc.py` revision as `634d58c0f6464b1454813153aba85c78e17ab3a0`.

## Authors, sources, and licensing evidence

| File | Attribution and upstream source | Licensing evidence |
| --- | --- | --- |
| `adjust.py` | dubhater and contributors; [vapoursynth-adjust](https://github.com/dubhatervapoursynth/vapoursynth-adjust) | The upstream README declares WTFPL without a version. A copy is included as [adjust-readme.rst](licenses/adjust-readme.rst). |
| `dfttest2.py` | AmusementClub and contributors; [vs-dfttest2 v9](https://github.com/AmusementClub/vs-dfttest2/tree/v9); script version `0.4.0` | Upstream supplies the GNU GPL version 3 text; included as [GPL-3.0.txt](licenses/GPL-3.0.txt). |
| `havsfunc.py` | HolyWu and contributors, modified by MIR; [base revision](https://github.com/HomeOfVapourSynthEvolution/havsfunc/tree/7f0a9a7a37b60a05b9f408024d203e511e544a61) | The base revision supplies the [Unlicense](licenses/havsfunc-Unlicense.txt). The MIR modifications have no separate license declaration in this snapshot. |
| `MCDenoise.py` | Mystery Keeper; [TempLinearApproximate upstream](https://bitbucket.org/mystery_keeper/templinearapproximate-vapoursynth/) | The copied script has no copyright or license header. The author's [release announcement](https://forum.doom9.org/archive/index.php/t-169782.html) describes a change to MIT for TempLinearApproximate; a complete license notice specifically accompanying this script was not available. |
| `mirvsfunc.py` | MIR / AmusementClub and contributors; [vapoursynth-script](https://github.com/AmusementClub/vapoursynth-script); script version `0.1.3` | No license declaration was found in the copied file or the consulted upstream repository. |
| `muvsfunc.py` | WolframRhodium and contributors; [recorded distribution revision](https://github.com/WolframRhodium/muvsfunc/tree/634d58c0f6464b1454813153aba85c78e17ab3a0) | No license declaration was found in the copied file or the consulted upstream repository. |
| `muvsfunc_numpy.py` | WolframRhodium and contributors; [muvsfunc collections](https://github.com/WolframRhodium/muvsfunc/tree/master/Collections) | No license declaration was found in the copied file or the consulted upstream repository. Embedded credits for reused implementations are retained. |
| `mvsfunc.py` | mawen1250 and contributors; [mvsfunc](https://github.com/HomeOfVapourSynthEvolution/mvsfunc) | No license declaration was found in the copied file or the consulted upstream repository. |
| `nnedi3_resample.py` | HomeOfVapourSynthEvolution contributors; [nnedi3_resample](https://github.com/HomeOfVapourSynthEvolution/nnedi3_resample) | No license declaration was found in the copied file or the consulted upstream repository. |
| `vsmlrt.py` | AmusementClub and contributors; [vs-mlrt](https://github.com/AmusementClub/vs-mlrt); script version `3.22.35` | Upstream supplies the GNU GPL version 3 text; included as [GPL-3.0.txt](licenses/GPL-3.0.txt). Model and inference-backend licenses are separate from this Python script. |
| `vsTAAmbk.py` | HomeOfVapourSynthEvolution contributors; [vsTAAmbk](https://github.com/HomeOfVapourSynthEvolution/vsTAAmbk) | No license declaration was found in the copied file or the consulted upstream repository. |

An unspecified license is not an MIT, public-domain, or unrestricted-use declaration. This notice records the available evidence and does not supply a missing permission or relicense an upstream modification.

## Distribution locations

Windows and Linux setup install the `.py` files into the selected VapourSynth Python search directory and this notice tree into its `licenses/vapoursynth_scripts/` directory. Docker installs the same files into its Python `dist-packages` directory. The Windows application bundle includes the scripts beside the shared Python runtime and this notice tree at `legal/vapoursynth_scripts/`.
