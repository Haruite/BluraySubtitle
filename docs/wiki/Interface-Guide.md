# Interface Guide and Examples

English | [简体中文](Interface-Guide.zh-Hans.md)

> These sample-disc screenshots illustrate the controls; layout and defaults can vary by version. Follow the current interface.

## Main-window content areas

The language, theme, font, and settings bar at the top and the execution button at the bottom stay fixed. Use the page scrollbar on the right for the remaining content. Separate table sections describe disc playlists, main outputs, and SP; each table scrolls independently for more rows or columns. Drag the handle below each table to adjust its height; drag column borders to resize them and hover for full text. Disc information rows can also be made taller to show more MPLS entries. Always check automatically generated rows against the actual content.

The *Witch Craft Works* example selects the first two discs for 12 TV episodes and leaves the bonus disc for separate processing. Check the estimated episode boundaries against the content: here EP05 and EP11 end at Chapter 31, which also becomes the start of the following episode. The SP table shows short clips and `igs_menu` entries; interactive menu graphics cannot become ordinary Matroska subtitle tracks.

[![Witch Craft Works joined-disc interface](https://sbx.mysmy.top/pictures/interface-20260910-joined-disc-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-joined-disc-en.jpg)

## Disc selection and order

Use the checkbox beside each disc path to choose which volumes to process. Drag a path row before or after another row to set the disc order; clicking a column heading sorts the rows by that column. Unchecked discs remain visible, but their main outputs and SP are excluded.

Changing the disc selection or order regenerates the dependent output tables. Review episode numbering, output names, chapter ranges, and attached subtitles before starting. The disc-number column refers to the current source row, including unchecked rows; episode numbering follows the selected content.

The *Spice and Wolf* folder names sort as volume 2, volume 4, DISC 1, and volume 3. The screenshot shows DISC 1 in the third source row before manual reordering. Drag the paths into story order, then check the regenerated episode numbers and filenames. Review each volume's chapter boundaries and SP selection as well.

[![Spice and Wolf multi-volume interface](https://sbx.mysmy.top/pictures/interface-20260910-disc-order-input-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-disc-order-input-en.jpg)

### Mixed directories and ISO files for subtitle merging

*Fullmetal Alchemist: Brotherhood* illustrates a source folder containing both ISO files and extracted disc directories. In **Merge Subtitles**, an ISO supplies its playlists without extracting the media; ISO preview, Remux, and Encode are unsupported. Sort by the full path and check the volume numbers before matching subtitles. Here volume 11 is an ISO and volume 12 is a directory.

[![Fullmetal Alchemist mixed ISO and directory sources](https://sbx.mysmy.top/pictures/interface-20260910-mixed-iso-subtitles-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-mixed-iso-subtitles-en.jpg)

## Example: two movie versions on one disc

In **Movie mode**, *Black Hawk Down* selects `00501.mpls` and `00503.mpls`, with durations 02:24:18.649 and 02:31:50.601. The output table gives them distinct `_1` and `_2` filenames. Their complete duplicate alternatives, `00502.mpls` and `00504.mpls`, are left unchecked.

[![Black Hawk Down two selected movie versions](https://sbx.mysmy.top/pictures/interface-20260910-movie-two-versions-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-movie-two-versions-en.jpg)

Multiple long playlists do not necessarily mean multiple editions. For example, *Zootopia 2* keeps one main `00800.mpls`; inspect content and track differences before selecting additional main playlists.

## Inspecting MPLS chapters, PlayItems, and tracks

**View chapters**, **View timing**, and **Edit tracks** show different layers of the same MPLS. Chapters are useful for choosing output ranges, M2TS time shows the exact source interval used by each PlayItem, and track editing determines which logical tracks reach the final output.

### View chapters

**View chapters** lists chapter intervals on the output timeline and their M2TS files. In Remux/Encode, unchecking an interval of a selected main MPLS excludes it from that main output; review the resulting SP rows separately. The chapter dialog for a non-main playlist is read-only. To edit its chapter selection, first select that playlist as a main MPLS.

[![Zootopia 2 chapter view](https://sbx.mysmy.top/pictures/interface-20260910-movie-chapters-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-movie-chapters-en.jpg)

#### Excluding interleaved audio dramas

*ODDTAXI* interleaves TV episodes and audio dramas in each disc's `00000.mpls`. Keep those main playlists and uncheck the drama intervals in **View chapters**:

- Disc 1: Chapters 6, 12, 18, 24, 30, 35, and 41.
- Disc 2: Chapters 5, 11, 17, 22, 28, and 31.

This produces 7 + 6 TV episode ranges. The excluded dramas appear as separate chapter-segment SP rows, where you can decide whether to keep them. The screenshot shows the beginning of disc 1's chapter selection.

[![ODDTAXI audio-drama chapter intervals unchecked](https://sbx.mysmy.top/pictures/interface-20260910-audio-drama-chapters-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-audio-drama-chapters-en.jpg)

### View M2TS time

**View timing** lists each PlayItem's M2TS, `INTime`, `OUTTime`, duration, and start/end positions on the MPLS timeline. The IN/OUT columns use 45 kHz ticks; duration and timeline positions use timecodes. An MPLS commonly references only part of an M2TS, so “this M2TS is used” does not mean that the complete file should be copied.

[![Zootopia 2 M2TS time view](https://sbx.mysmy.top/pictures/interface-20260910-movie-playitems-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-movie-playitems-en.jpg)

### Edit tracks

In **Edit tracks**, check the desired rows and hover over status for per-PlayItem details. See the [STN model](Blu-ray-Disc-Structure.md#stn-table) for logical-track identity and format restrictions.

In the *Zootopia 2* example, audio and subtitle status directly shows `eng → zho → eng`, while the tooltip lists the language and PID for each group of PlayItems. A language change is informational and does not split one logical track into several tracks.

[![Zootopia 2 Edit tracks dialog](https://sbx.mysmy.top/pictures/interface-20260910-movie-tracks-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-movie-tracks-en.jpg)

The *Avatar: The Way of Water* `00150.mpls` audio row marked **Missing in some clips** does not cover every PlayItem. Actual M2TS omissions are subject to the [partial-missing option](../../README.md#remux-controls).

[![Avatar: The Way of Water track missing in some clips](https://sbx.mysmy.top/pictures/interface-20260910-missing-track-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-missing-track-en.jpg)

## Example: avoiding Remux growth from duplicated clips

*Hana-Kimi* contains 12 regular episodes plus three Non Credit (NC) editions, one on each of the first three volumes. Some MPLS content overlaps. Remuxing every playlist as independent content writes the same physical clips into several outputs, so the combined output size can exceed the disc's unique stored content. This is a typical case covered by the README FAQ question “Why is remux larger than the original disc?”.

On volume 2, both `00000.mpls` and `00001.mpls` cover three episodes. Their references to `00001.m2ts` and `00003.m2ts` duplicate the same content, while `00005.m2ts` is the NC edition corresponding to the episode stored in `00004.m2ts`. Select both playlists as main MPLS entries. Keep all normal chapter intervals in `00000.mpls`:

[![Hana-Kimi volume 2 00000.mpls](https://sbx.mysmy.top/pictures/interface-20260910-hana-regular-chapters-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-hana-regular-chapters-en.jpg)

In `00001.mpls`, uncheck the first 12 duplicated chapter intervals and retain the NC content beginning at Chapter 13. This keeps the three regular episodes and the additional NC edition without writing the repeated episodes twice.

[![Hana-Kimi volume 2 00001.mpls chapter selection](https://sbx.mysmy.top/pictures/interface-20260910-hana-nc-chapters-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-hana-nc-chapters-en.jpg)

The volume-2 output rows now contain three regular episodes and one NC edition. The extra main output also occupies an episode number, so review its filename and subsequent numbering before starting. Check the SP table for any additional overlapping content you do not want to export.

[![Hana-Kimi series Remux interface](https://sbx.mysmy.top/pictures/interface-20260910-hana-outputs-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-hana-outputs-en.jpg)

## Example: why INTime and OUTTime must be honored

On *I Was Reincarnated as the 7th Prince* season 2 volume 1, `00004.mpls` is the NC presentation of episode 1. Its main content comes from the episode's `00002.m2ts`, while `00009.m2ts` and `00010.m2ts` are NC segments. The chapter dialog shows the completed MPLS timeline:

[![Seventh Prince season 2 volume 1 00004.mpls chapters](https://sbx.mysmy.top/pictures/interface-20260910-nc-splice-chapters-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-nc-splice-chapters-en.jpg)

The M2TS time view shows separate ranges from `00002.m2ts` interleaved with `00009.m2ts` and `00010.m2ts`. Copying whole M2TS files while ignoring `INTime` and `OUTTime` would include content that the playlist never references and would not reproduce the authored NC presentation.

[![Seventh Prince season 2 volume 1 00004.mpls PlayItems](https://sbx.mysmy.top/pictures/interface-20260910-nc-splice-playitems-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-nc-splice-playitems-en.jpg)

## Example: a complete matching MPLS supplies another track

On *Re:Zero* season 3 volume 1, `00001.mpls` and the complete-timeline match `00002.mpls` each expose a PCM audio track. The application displays both in one **Edit tracks** dialog and identifies their source MPLS. Both can enter the same main output when their physical M2TS/PID relations do not overlap. The IGS row remains visible but disabled because Matroska cannot represent interactive graphics as an ordinary subtitle track.

[![Re:Zero season 3 volume 1 complete-MPLS track attachment](https://sbx.mysmy.top/pictures/interface-20260910-whole-playlist-tracks-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-whole-playlist-tracks-en.jpg)

See [Blu-ray Disc Structure: SP tracks and MPLS-hidden tracks](Blu-ray-Disc-Structure.md#sp-tracks-and-mpls-hidden-tracks) for the complete rule.

## Example: two commentary providers for one episode

On *Frieren: Beyond Journey's End* season 2 volume 3, `00004.mpls` and `00005.mpls` match the first episode and expose different commentary audio tracks, PIDs 4353 and 4354. With all three volumes selected, both SP rows name the same EP08 output. Each row appends its selected tracks to that episode; open **Edit tracks** on both rows to review them.

[![Frieren two commentary playlists attached to EP08](https://sbx.mysmy.top/pictures/interface-20260910-episode-commentary-providers-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-episode-commentary-providers-en.jpg)

The duration column shows the source playlist duration. A repeating menu can therefore show a much longer time than the clip retained by the menu processing rules; check its PlayItems when reviewing such a row.

## Example: a bonus disc without main episodes

Keep *Sonny Boy*'s BONUS disc checked in the source table, but uncheck its `00035.mpls` main-playlist button. The two TV discs then provide 12 main episodes, and the bonus disc contributes SP outputs.

[![Sonny Boy BONUS disc checked with no main playlist](https://sbx.mysmy.top/pictures/interface-20260910-bonus-disc-no-main-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-bonus-disc-no-main-en.jpg)

The complete 48:52.805 feature becomes `BD_Vol_003_SP06.mkv`, with its existing chapter range. The same table also shows PNG and image-directory outputs for still content. Review their selections and names using the [SP output rules](Blu-ray-Disc-Structure.md#sp-selection-and-outputs).

[![Sonny Boy complete bonus feature and still-image SP outputs](https://sbx.mysmy.top/pictures/interface-20260910-bonus-disc-sp-en.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-bonus-disc-sp-en.jpg)

## Suggested workflow

1. Choose the main MPLS from duration and playback results, not from its number alone.
2. Use **View chapters** to define the movie or episode output ranges.
3. Use **View timing** to check duplicated clips, clip order, and `INTime`/`OUTTime`.
4. Confirm final video, audio, and subtitle choices in **Edit tracks**, and read the tooltip for any exceptional status.
5. Review the SP table last and uncheck duplicated, unwanted, or unnecessary standalone items.
