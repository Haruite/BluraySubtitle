# Blu-ray Disc Structure

This page follows a Blu-ray title from the directory tree down to transport
packets. It focuses on the structures that BluraySubtitle reads and the timing
rules that determine what a playlist actually plays.

## The disc root

A movie Blu-ray normally exposes two directories at the filesystem root:

```text
BDROM/
├── BDMV/
└── CERTIFICATE/
```

`CERTIFICATE` participates in disc/application authenticity and is not part of
the media extraction path described here. `BDMV` holds the playback
application and audiovisual content.

Commercial discs may also contain encryption or protection-related data. AACS
and BD+ operate below or beside the playlist/container concerns described on
this page. BluraySubtitle expects the operating system to expose readable
files; it is not an AACS or BD+ decrypter.

## The BDMV directory

A representative tree is:

```text
BDMV/
├── index.bdmv
├── MovieObject.bdmv
├── PLAYLIST/
│   ├── 00000.mpls
│   └── ...
├── CLIPINF/
│   ├── 00000.clpi
│   └── ...
├── STREAM/
│   ├── 00000.m2ts
│   └── ...
├── BACKUP/
│   ├── index.bdmv
│   ├── MovieObject.bdmv
│   ├── PLAYLIST/
│   └── CLIPINF/
├── AUXDATA/          (optional)
├── META/             (optional)
├── BDJO/             (BD-J, optional)
└── JAR/              (BD-J, optional)
```

The important relationships are:

```text
index.bdmv
    └─ title entry
       └─ MovieObject.bdmv or BD-J object
          └─ starts a playlist
             └─ PLAYLIST/xxxxx.mpls
                ├─ selects one or more clip windows
                │  ├─ CLIPINF/yyyyy.clpi
                │  └─ STREAM/yyyyy.m2ts
                └─ defines playlist marks and stream entries
```

### `index.bdmv`

The index table defines top-level title entry points, first playback, and menu
entry behavior. A title refers to HDMV movie objects or BD-J applications.

### `MovieObject.bdmv`

Movie objects contain navigation commands interpreted by the HDMV virtual
machine. Commands can start playlists, jump between objects, update player
registers, and react to navigation events.

BluraySubtitle does not emulate the full navigation application. Its task is to
identify and process authored playlists and clips.

### `PLAYLIST`

Each `xxxxx.mpls` is a **Movie PlayList**. It defines an ordered virtual
timeline made from one or more clip intervals. It can also contain stream
selection metadata, subpaths, multi-angle references, and playlist marks.

### `CLIPINF`

Each `xxxxx.clpi` describes the corresponding `STREAM/xxxxx.m2ts`. CLPI contains
clip timing, program and stream metadata, and indexes that allow a player to map
presentation time to transport-stream packet positions.

### `STREAM`

Each `xxxxx.m2ts` stores multiplexed audiovisual packets. The filename alone
does not identify whether the file is main content, an extra, a menu, a still,
audio-only material, or a reusable branch.

### `BACKUP`

The important navigation and clip-information structures are duplicated under
`BACKUP`. The large `STREAM` directory is not duplicated. Software may consult
backup copies when primary metadata is missing or damaged.

### Optional content

- `AUXDATA` can hold auxiliary sound and font data.
- `META` can hold XML metadata and images.
- `BDJO` and `JAR` support BD-J applications.
- Interactive menu graphics usually live as streams inside M2TS rather than as
  ordinary image files.

## Special authored content

A disc is a playback application, not just a collection of movie files. Small
or unusual streams can be required for menus and navigation and should not be
discarded merely because they have almost no duration.

### HDMV/BD-J menus and IGS

Blu-ray has two principal navigation models:

- **HDMV** menus use commands in `MovieObject.bdmv` and graphical/menu streams;
- **BD-J** titles use Java applications from `BDJO`/`JAR`, together with the
  disc's media and graphics resources.

An HDMV menu is commonly composed from separate planes:

1. a video or still-picture background;
2. an **IGS** (Interactive Graphics Stream, stream type `0x91`) containing menu
   pages, button groups, object bitmaps, palettes, and normal/selected/activated
   states; and
3. navigation commands that decide what a button does.

IGS is therefore not an ordinary subtitle and not necessarily a complete menu
image by itself. A representative extracted button-state PNG is useful for
inspection or preservation, but it does not reproduce the HDMV virtual machine,
BD-J application, user-operation masks, sound effects, or all state transitions.

BluraySubtitle classifies an M2TS containing IGS without video as `igs_menu`.
For supported SP output it reconstructs page/state images from palette, object,
and composition segments. This preserves inspectable graphics, not interactive
disc navigation.

### Still pictures and one-frame video

A menu background or gallery item may be a genuine video stream containing only
one decoded frame. The playlist can keep that frame visible rather than storing
seconds or minutes of duplicate frames. The corresponding M2TS can consequently
be very small and report a near-zero media duration without being corrupt.

MPLS `PlayItem` also has authored still-playback fields:

| `StillMode` | Meaning |
| ---: | --- |
| `0` | Normal playback; no playlist still |
| `1` | Hold the final presentation for `StillTime` seconds |
| `2` | Hold indefinitely until navigation continues |

The physical one-frame stream and the playlist still instruction are related
but distinct. Counting frames in the M2TS does not reveal how long a disc player
will keep it on screen; `StillMode`, `StillTime`, and navigation behavior must
also be considered.

During SP scanning, BluraySubtitle treats very small video sources (currently
no more than 1 MiB per involved M2TS) with at most one known frame per source as
single-frame or multi-clip still content. The size check is an early
classification guard, not a Blu-ray specification limit. Unknown frame count,
audio-only content, and larger streams follow other classification paths.

### Other non-feature layouts

Original discs may also contain:

| Layout | Typical purpose | Preservation concern |
| --- | --- | --- |
| Audio-only M2TS | Menu music, commentary, sound program | Do not require a video track |
| Subtitle-only or audio-plus-subtitle M2TS | Auxiliary presentation streams | Choose `.mks`, `.mka`, or a suitable container from selected tracks |
| M2TS not referenced by any MPLS | Orphaned resource or directly accessed menu asset | Playlist-only discovery would miss it |
| Multi-angle PlayItem | Alternate camera/credit/language angle | One MPLS interval can reference alternative clips |
| Secondary video/audio and SubPaths | Picture-in-picture, commentary, MVC dependent view | They are not always part of the primary linear stream |
| Seamless branching | Multiple cuts sharing common clips | File size and filename order do not identify one final title |

This is why BluraySubtitle lists useful unreferenced M2TS files and classifies
track composition instead of assuming every SP is an ordinary short video.

## Playing an original disc and checking an MPLS

Playing a BDMV folder is useful for confirming the main feature, but different
entry methods do not provide the same semantics.

### PotPlayer folder playback

On Windows, a BDMV/original-disc folder can be dragged into PotPlayer. In this
mode it commonly behaves like automatic title selection, often choosing the
longest-duration MPLS. That is convenient for a quick check but can select the
wrong playlist on episodic discs, seamless-branching editions, playlists with
duplicated clips, or discs authored to confuse longest-title heuristics.

This folder-drag path should not be treated as proof of the authored main MPLS.
It also does not provide the full original-disc navigation experience in this
workflow. Verify the clip order, chapters, languages, and visible content, then
select the intended MPLS explicitly in BluraySubtitle.

### mpv playlist playback

mpv's Blu-ray input is a URL-style command, not ordinary opening of the
`.mpls` file:

```powershell
mpv "bd://mpls/00001" --bluray-device="D:\Disc"
```

`00001` selects `BDMV/PLAYLIST/00001.mpls`, and `--bluray-device` points to the
disc root containing `BDMV`. A general `bd://` command may choose a default
title such as `longest` or `first`; use `bd://mpls/<number>` when verifying one
specific playlist. The mpv build needs libbluray support, and protected content
must already be readable.

BluraySubtitle integrates this command behind the playlist/SP **Play** button.
When mpv is configured on Windows, the GUI passes the exact selected MPLS ID and
disc root and can add a matching external subtitle for preview. If no usable mpv
is configured, Windows falls back to the operating-system file association,
whose playlist-selection behavior depends on the associated player.

Direct MPLS playback intentionally bypasses authored top-menu navigation. It is
for verifying a selected playlist, not for emulating the complete disc
application.

## MPLS, M2TS, and CLPI: how they work together

The three names answer different questions:

| Structure | Main responsibility |
| --- | --- |
| MPLS | Which clips, in which order, and which time interval of each clip? |
| CLPI | What timing/program/index information describes one M2TS clip? |
| M2TS | Where are the actual multiplexed video, audio, and graphics packets? |

An MPLS `PlayItem` contains a five-character
`ClipInformationFileName`. For `00042`, the logical relationship is:

```text
PLAYLIST/xxxxx.mpls
  PlayItem.ClipInformationFileName = "00042"
                       │
                       ├── CLIPINF/00042.clpi
                       └── STREAM/00042.m2ts
```

The MPLS does not normally embed the video or audio. The M2TS does not by
itself say which portion the title should play. The CLPI provides the timing
and stream description needed to navigate the M2TS correctly.

## MPLS binary layout

An MPLS begins with a header containing:

- a four-byte type indicator, normally `MPLS`;
- a four-byte version indicator;
- `PlayListStartAddress`;
- `PlayListMarkStartAddress`;
- `ExtensionDataStartAddress`; and
- reserved bytes.

The major sections are:

1. `AppInfoPlayList`;
2. `PlayList`, containing `PlayItem` and `SubPath` entries;
3. `PlayListMark`; and
4. optional extension data.

The addresses are byte offsets from the start of the file. Parsers should use
the offsets and declared lengths rather than assuming that variable-sized
sections immediately follow one another.

### PlayList

The playlist section contains:

- `NumberOfPlayItems`;
- `NumberOfSubPaths`;
- an ordered list of `PlayItem` records; and
- an ordered list of `SubPath` records.

The main linear timeline comes from the `PlayItem` list. Subpaths can carry
secondary or synchronized material such as picture-in-picture content.

### PlayItem

A play item includes:

| Field | Meaning |
| --- | --- |
| `ClipInformationFileName` | Five-digit clip identifier |
| `ClipCodecIdentifier` | Normally `M2TS` |
| `IsMultiAngle` | Whether alternative clip references follow |
| `ConnectionCondition` | How this item joins its neighbor |
| `RefToSTCID` | Referenced system-time-clock sequence |
| `INTime` | First authored presentation time |
| `OUTTime` | End of the authored presentation interval |
| `UOMaskTable` | User-operation restrictions |
| `StillMode` / `StillTime` | Still-frame behavior |
| `STNTable` | Streams visible for this play item |

Multi-angle items contain additional clip identifiers and STC references.
Different angles may reuse audio or carry different audio, depending on the
flags.

### `INTime` and `OUTTime`

MPLS play-item times use a **45 kHz clock**:

```text
duration_seconds = (OUTTime - INTime) / 45,000
```

These values are timestamps within the referenced STC sequence, not byte
offsets and not necessarily seconds from the physical beginning of the M2TS
file.

The transport stream commonly expresses PTS, DTS, and the PCR base on a
**90 kHz clock**. The basic conversion is:

```text
mpls_timestamp_90k = mpls_timestamp_45k × 2
```

To express a playlist boundary relative to the first usable presentation
timestamp in an M2TS, BluraySubtitle uses the relationship:

```text
start_seconds = (INTime × 2 - first_m2ts_pts) / 90,000
end_seconds   = start_seconds + (OUTTime - INTime) / 45,000
```

This explains why treating `INTime / 45,000` as a simple file-relative seek can
be wrong. M2TS clips often start on a non-zero transport timeline, and a
playlist can select only an interior interval.

`OUTTime` describes the end boundary of the authored interval. Whether an
individual access unit exactly on that boundary is included can depend on
stream type and demuxer semantics. Code that cuts video, audio, PG, and IG
streams must respect the tool’s boundary behavior rather than assuming one
universal inclusive rule.

### STN table

`STN` means **Stream Number**. A play item’s `STNTable` describes streams that
the playlist exposes, grouped into categories such as:

- primary video;
- primary audio;
- primary Presentation Graphics;
- primary Interactive Graphics;
- secondary audio;
- secondary video;
- secondary Presentation Graphics; and
- Dolby Vision or extension-defined entries.

Each entry combines:

- a `StreamEntry`, which identifies a transport PID directly or through a
  subpath/subclip relationship; and
- `StreamAttributes`, which describe coding type, video format/frame rate,
  audio format/sample rate, language, and related fields.

This distinction matters in BluraySubtitle. PAT/PMT parsing can reveal streams
physically present in an M2TS, while the MPLS STN table defines the streams
authored as visible for that playback path. A physically present stream hidden
by the playlist must not automatically be treated as selected title content.

### Playlist marks and chapters

The `PlayListMark` section contains entries with:

- `MarkType`;
- `RefToPlayItemID`;
- `MarkTimeStamp`;
- `EntryESPID`; and
- `Duration`.

An entry mark commonly becomes a chapter. Its timestamp belongs to the
referenced play item’s timebase. To place it on the continuous playlist
timeline:

```text
chapter_seconds =
    sum(duration of all earlier play items)
    + (MarkTimeStamp - referenced_item.INTime) / 45,000
```

Marks are metadata, not cuts. A chapter indicates a navigation point. Splitting
at a chapter without re-encoding is only exact when the involved streams and
container can begin cleanly at that point, normally around a random-access
video frame.

## CLPI binary layout

A CLPI header contains addresses for:

- `SequenceInfo`;
- `ProgramInfo`;
- `CPI`;
- clip marks; and
- optional extension data.

### Sequence information

Sequence information divides the clip into arrival-time-clock and
system-time-clock sequences. An STC sequence records:

- PCR PID;
- starting source-packet number;
- presentation start time; and
- presentation end time.

An MPLS play item’s `RefToSTCID` identifies the relevant STC sequence. This is
the clock context in which `INTime` and `OUTTime` are interpreted.

### Program information

Program information describes programs and their streams, including:

- program-map PID;
- stream count;
- each stream PID; and
- coding information such as codec type, format, sample rate, and language.

The project uses this information when repairing or reconstructing playlist
stream tables.

### CPI

The **Characteristic Point Information** index maps presentation times to
source-packet numbers at usable access points. A player or demuxer can use it
to seek near the requested playlist time without scanning the entire M2TS.

BluraySubtitle’s lightweight CLPI parser currently reads sequence and program
information. Its primary high-level workflows rely on playlist windows,
transport timestamps, MKVToolNix, and targeted recovery paths rather than
implementing the complete CLPI CPI seek model itself.

## M2TS binary layout

Blu-ray M2TS is based on MPEG-2 Transport Stream, with a four-byte prefix added
to every 188-byte TS packet:

```text
M2TS source packet: 192 bytes
├── TP_extra_header: 4 bytes
└── MPEG-2 TS packet: 188 bytes
    ├── fixed header
    ├── optional adaptation field
    └── optional payload
```

Thirty-two 192-byte source packets form a 6,144-byte aligned unit:

```text
32 × 192 = 6,144 bytes = 3 × 2,048-byte logical sectors
```

The standard TS sync byte is `0x47`, found at byte offset 4 of each normal
M2TS source packet. This gives a practical alignment check:

```text
offset 4, 196, 388, 580, ... should contain 0x47
```

BluraySubtitle can also detect plain 188-byte TS input and unusual 192-byte
layouts by sampling for repeated sync positions.

### Transport packet header

The 188-byte TS packet header includes:

- sync byte `0x47`;
- transport-error indicator;
- payload-unit-start indicator (`PUSI`);
- transport priority;
- 13-bit packet identifier (`PID`);
- scrambling control;
- adaptation-field control; and
- four-bit continuity counter.

The PID identifies which logical stream or table the packet belongs to. The
continuity counter helps detect missing, duplicated, or reordered packets for a
PID. An adaptation field can carry PCR and other timing/control information.

### PAT and PMT

The **Program Association Table** is carried on PID `0x0000`. It maps a program
number to the PID of its **Program Map Table**.

The PMT then lists:

- the PCR PID;
- elementary-stream PIDs;
- stream type codes; and
- descriptors such as language or registration information.

PAT and PMT sections can span multiple TS packets. A parser must honor PUSI,
pointer fields, declared section lengths, and multi-packet assembly. Scanning
only the first payload fragment is unreliable, especially for UHD titles with
large PMTs.

### PES, PTS, DTS, and PCR

Video, audio, and graphics elementary data is commonly wrapped in
**Packetized Elementary Stream** packets before being divided across TS
packets.

- **PTS** says when a presentation unit should be presented.
- **DTS** says when it should be decoded when decoding order differs from
  presentation order.
- **PCR** provides the program clock reference used to synchronize the
  decoder’s timebase.

PTS/DTS and the PCR base use 90 kHz units. PCR also has a finer 27 MHz
extension, which is unnecessary for the project’s clip-duration calculation.

Timestamp values wrap because their fields have finite width. Duration code
must use modular arithmetic when a clip crosses the wrap point.

## Common Blu-ray stream type codes

The following values are especially relevant to the project:

| Code | Stream |
| ---: | --- |
| `0x02` | MPEG-2 video |
| `0x1B` | AVC/H.264 video |
| `0x20` | MVC dependent video |
| `0x24` | HEVC/H.265 video |
| `0xEA` | VC-1 video |
| `0x80` | Blu-ray LPCM |
| `0x81` | AC-3 |
| `0x82` | DTS core |
| `0x83` | TrueHD |
| `0x84` | E-AC-3 |
| `0x85` | DTS-HD High Resolution |
| `0x86` | DTS-HD Master Audio |
| `0x90` | Presentation Graphics (PGS) |
| `0x91` | Interactive Graphics (IGS) |
| `0x92` | Text Subtitle (TextST) |

Descriptors and Blu-ray extensions can refine the meaning. A stream type code
alone is not sufficient to describe every Dolby Vision or private-stream
variant.

## Why playlist-aware processing is required

### Interior clip windows

If a play item selects only 10:00–20:00 of a one-hour M2TS, concatenating the
whole M2TS produces the wrong title. A demuxer must apply both boundaries in the
correct STC/PTS timebase.

### Reused clips

One M2TS can appear in multiple playlists or multiple times in one playlist.
The same physical bytes can therefore contribute to main content, SP content,
or both, depending on the selected interval.

### Seamless branching

Different editions or cuts can share most clips but choose different branches.
The playlist, not file size or filename order, expresses the desired cut.

### Different track layouts

Adjacent clips may not contain identical PIDs. A direct append can lose tracks,
change track order, or fail. BluraySubtitle’s fallback aligns each clip to the
selected reference layout before appending.

### Playlist obfuscation

Some discs contain many plausible playlists with deliberately permuted clip
orders. “Longest playlist” is then a weak heuristic. Playback inspection or
external knowledge may be necessary to choose the correct main MPLS.

## How the automatic main-playlist estimate works

BluraySubtitle uses a multi-factor estimate to choose the initially selected
main MPLS. It is a convenience for opening a disc, not a claim that the
selected playlist is authoritatively correct:

```text
score =
    non-repeated playlist duration
    × (1 + playlist-mark count / 5)
    × MPLS file size
    × total size of distinct referenced M2TS files
```

Repeated references to the same clip name contribute only once to the
non-repeated duration and M2TS-size terms.

The MPLS file size matters because two playlists can have exactly the same
clip list and `INTime`/`OUTTime` windows while exposing different numbers of
tracks. This occurs on some large movie discs. The playlist with the fuller
STN tables is usually the useful one, and it is commonly the larger MPLS file.
File size is only a proxy for playlist metadata and track entries, so manual
track inspection remains the definitive check.

The last term is the **sum** of all different referenced M2TS file sizes,
multiplied into the score; the individual file sizes are not multiplied by one
another. This prevents a menu-like playlist from looking important merely
because it repeats the same small M2TS many times. Counting repeated duration
without considering the amount of distinct stream data would make such
playlists easy to misclassify.

Some movie discs—Disney releases are a common example—contain several
same-duration playlists that choose different files but produce little or no
visible difference. BluraySubtitle does not decode and compare these variants.
When candidates have exactly the same score, the first one encountered remains
the default because only a strictly higher score replaces it. This is directory
enumeration order, not a guaranteed numeric filename order. Select another
playlist manually when a language, localization, branch, or edition difference
matters.

## Episodic layouts and MPLS-based slicing

The following names are community terminology, not Blu-ray specification
terms.

### Continuous-clip or “joined” discs (连体盘)

A joined episodic disc stores several episodes consecutively in one large
M2TS. The main playlist selects windows inside that clip, and episode
boundaries may be represented by playlist marks or derived file/time
boundaries. Treating the M2TS as one episode would therefore merge the whole
disc.

### Fragmented-episode or “roujiang” discs (肉酱盘)

A roujiang disc assembles one episode from several M2TS files. Complex examples
do not have a one-to-one relationship between clips and chapters: one M2TS may
have no playlist mark, while another may contain several marks. Neither “one
M2TS equals one episode” nor “one mark equals one M2TS” is a safe rule.

BluraySubtitle handles both layouts through its MPLS-based slicing model. It
uses the ordered play-item windows and the derived chapter/file boundary
timeline, then builds episode ranges from that playlist timeline. It does not
require the physical M2TS layout to match episode boundaries.

### One master playlist or one playlist per episode

Anime discs commonly have one main MPLS that concatenates every episode.
Some discs instead expose one MPLS per episode and require the viewer to choose
episodes individually in the authored disc interface. The latter layout is
especially common on US television releases. BluraySubtitle allows multiple
main MPLS selections; select the episode playlists and keep them in the desired
processing order.

### Short copyright bumpers at the end

Many anime playlists end with a separate copyright-information M2TS, often
about eight seconds long. Removing it normally does not affect the episode.
The **View Chapters** dialog can uncheck displayed segments, but the episode
start/end selectors use authored chapter marks. The final M2TS often begins
between chapter marks, so chapter-only selection cannot isolate that boundary.

For this case, episode-mode remux and encode workflows provide **Trim copyright
bumper**. The option works at the playlist model rather than requiring a
chapter mark: when the playlist contains at least two play items, it removes
the final play item if its window is shorter than 15 seconds and discards marks
that belong to that item. The source MPLS is not modified. Because a legitimate
short tail can satisfy the same rule, verify unusual discs before leaving the
option enabled.

## Main content and SP in this project

The Blu-ray specification does not define “main MPLS” or “SP” as used here.
BluraySubtitle applies a content model on top of the disc:

- A **main MPLS** is a selected playlist whose authored playback content is the
  main movie or episodes.
- Selected chapter/segment ranges inside it form main outputs.
- Unchecked ranges inside the main playlist are SP candidates.
- Other playlists are SP candidates.
- M2TS files not covered by any playlist can also become SP rows when their
  content can be handled deterministically.

Therefore:

```text
disc content
├── selected main-playlist intervals → main outputs
└── remaining useful authored or uncovered content → SP
```

“SP” can include ordinary video extras, menus, audio-only material,
subtitle-only material, IGS assets, and single-frame images. It does not imply
one codec or container.

## Validation checklist for a playlist

When deciding whether an MPLS is main content:

1. Play or inspect the playlist, not only its filename.
2. Check the ordered clip list and every `INTime`/`OUTTime` window.
3. Compare duration with the expected movie or episode duration.
4. Inspect chapters and branch points.
5. Confirm video, audio, and subtitle streams exposed by the STN table.
6. Look for repeated or permuted playlists.
7. Check whether part of the playlist is a bumper, warning, menu, or unrelated
   material that should be unchecked and treated as SP.
8. Confirm that multiple legitimate main playlists are not being collapsed into
   one assumption.
