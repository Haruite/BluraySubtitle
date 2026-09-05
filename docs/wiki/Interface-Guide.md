# Interface Guide and Examples

English | [简体中文](Interface-Guide.zh-Hans.md)

> These sample-disc screenshots illustrate the controls; layout and defaults can vary by version. Follow the current interface.

## Main-window content areas

After loading a BDMV, series-mode Disc Remux mainly shows four kinds of information: MPLS information and mux commands for each volume at the top, planned episode outputs in the middle, SP items below them, and subtitle/output folders plus the start button at the bottom. Automatically generated rows are a starting point and are not guaranteed to be correct for every disc.

This joined-disc example from *Witch Craft Works* shows main episode ranges, short SP items, and `igs_menu` entries together. Verify the start and end chapters of each episode row. Menu IGS normally does not become an ordinary Matroska subtitle track.

[![Witch Craft Works joined-disc interface](https://sbx.mysmy.top/pictures/%E9%AD%94%E5%A5%B3%E7%9A%84%E4%BD%BF%E5%91%BD%20%E8%BF%9E%E4%BD%93%E7%9B%98.png)](https://sbx.mysmy.top/pictures/%E9%AD%94%E5%A5%B3%E7%9A%84%E4%BD%BF%E5%91%BD%20%E8%BF%9E%E4%BD%93%E7%9B%98.png)

This multi-volume *Spice and Wolf* example shows that every volume has its own main MPLS, episode rows, and SP items. Check episode boundaries and SP selections volume by volume; similar-looking tables do not imply identical authored content.

[![Spice and Wolf multi-volume interface](https://sbx.mysmy.top/pictures/%E7%8B%BC%E4%B8%8E%E9%A6%99%E8%BE%9B%E6%96%99%20%E8%82%89%E9%85%B1%E7%9B%98.png)](https://sbx.mysmy.top/pictures/%E7%8B%BC%E4%B8%8E%E9%A6%99%E8%BE%9B%E6%96%99%20%E8%82%89%E9%85%B1%E7%9B%98.png)

## Inspecting MPLS chapters, PlayItems, and tracks

**View chapters**, **View M2TS time**, and **Edit tracks** show different layers of the same MPLS. Chapters are useful for choosing output ranges, M2TS time shows the exact source interval used by each PlayItem, and track editing determines which logical tracks reach the final output.

### View chapters

**View chapters** lists chapter intervals on the output timeline and the M2TS containing each interval. For a main MPLS, unchecking an interval excludes it from that main output; useful unselected content can then be reviewed separately in the SP table.

[![Zootopia 2 chapter view](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E6%9F%A5%E7%9C%8B%E7%AB%A0%E8%8A%82.png)](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E6%9F%A5%E7%9C%8B%E7%AB%A0%E8%8A%82.png)

### View M2TS time

**View M2TS time** lists each PlayItem's M2TS, `INTime`, `OUTTime`, duration, and start/end positions on the MPLS timeline. An MPLS commonly references only part of an M2TS, so “this M2TS is used” does not mean that the complete file should be copied.

[![Zootopia 2 M2TS time view](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E6%9F%A5%E7%9C%8B%E6%97%B6%E9%97%B4.png)](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E6%9F%A5%E7%9C%8B%E6%97%B6%E9%97%B4.png)

### Edit tracks

In **Edit tracks**, check the desired rows and hover over status for per-PlayItem details. See the [STN model](Blu-ray-Disc-Structure.md#stn-table) for logical-track identity and format restrictions.

In the *Zootopia 2* example, audio and subtitle status directly shows `eng → zho → eng`, while the tooltip lists the language and PID for each group of PlayItems. A language change is informational and does not split one logical track into several tracks.

[![Zootopia 2 Edit tracks dialog](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E7%BC%96%E8%BE%91%E8%BD%A8%E9%81%93.png)](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E7%BC%96%E8%BE%91%E8%BD%A8%E9%81%93.png)

The *Avatar* row marked **Missing in some clips** does not cover every PlayItem. Actual M2TS omissions are subject to the [partial-missing option](../../README.md#remux-controls).

[![Avatar track missing in some clips](https://sbx.mysmy.top/pictures/%E9%98%BF%E5%87%A1%E8%BE%BE%2000150.mpls%20%E7%BC%96%E8%BE%91%E8%BD%A8%E9%81%93.png)](https://sbx.mysmy.top/pictures/%E9%98%BF%E5%87%A1%E8%BE%BE%2000150.mpls%20%E7%BC%96%E8%BE%91%E8%BD%A8%E9%81%93.png)

## Example: avoiding Remux growth from duplicated clips

*Hana-Kimi* contains 12 regular episodes plus three Non Credit (NC) editions, one on each of the first three volumes. Some MPLS content overlaps. Remuxing every playlist as independent content writes the same physical clips into several outputs, so the combined output size can exceed the disc's unique stored content. This is a typical case covered by the README FAQ question “Why is remux larger than the original disc?”.

[![Hana-Kimi series Remux interface](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3.png)](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3.png)

On volume 2, both `00000.mpls` and `00001.mpls` cover three episodes. Their references to `00001.m2ts` and `00003.m2ts` duplicate the same content, while `00005.m2ts` is the NC edition corresponding to the episode stored in `00004.m2ts`. Use `00000.mpls` for the regular episodes and keep its normal chapter intervals:

[![Hana-Kimi volume 2 00000.mpls](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3%20%E7%AC%AC%E4%BA%8C%E5%8D%B7%2000000.mpls.png)](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3%20%E7%AC%AC%E4%BA%8C%E5%8D%B7%2000000.mpls.png)

In `00001.mpls`, uncheck the first 12 duplicated chapter intervals and retain the NC content beginning at Chapter 13. Table 3 row 8 in the main-window screenshot is also unnecessary and should be unchecked. This keeps the three regular episodes and the additional NC edition without writing the regular content twice.

[![Hana-Kimi volume 2 00001.mpls chapter selection](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3%20%E7%AC%AC%E4%BA%8C%E5%8D%B7%2000001.mpls.png)](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3%20%E7%AC%AC%E4%BA%8C%E5%8D%B7%2000001.mpls.png)

## Example: why INTime and OUTTime must be honored

On *I Was Reincarnated as the 7th Prince* season 2 volume 1, `00004.mpls` is the NC presentation of episode 1. Its main content comes from the episode's `00002.m2ts`, while `00009.m2ts` and `00010.m2ts` are NC segments. The chapter dialog shows the completed MPLS timeline:

[![Seventh Prince season 2 volume 1 00004.mpls chapters](https://sbx.mysmy.top/pictures/%E8%BD%AC%E7%94%9F%E4%B8%83%E7%8E%8B%E5%AD%90%20%E7%AC%AC%E4%BA%8C%E5%AD%A3%20%E7%AC%AC%E4%B8%80%E5%8D%B7%2000004.mpls%20%E7%AB%A0%E8%8A%82.png)](https://sbx.mysmy.top/pictures/%E8%BD%AC%E7%94%9F%E4%B8%83%E7%8E%8B%E5%AD%90%20%E7%AC%AC%E4%BA%8C%E5%AD%A3%20%E7%AC%AC%E4%B8%80%E5%8D%B7%2000004.mpls%20%E7%AB%A0%E8%8A%82.png)

The M2TS time view shows separate ranges from `00002.m2ts` interleaved with `00009.m2ts` and `00010.m2ts`. Copying whole M2TS files while ignoring `INTime` and `OUTTime` would include content that the playlist never references and would not reproduce the authored NC presentation.

[![Seventh Prince season 2 volume 1 00004.mpls PlayItems](https://sbx.mysmy.top/pictures/%E8%BD%AC%E7%94%9F%E4%B8%83%E7%8E%8B%E5%AD%90%20%E7%AC%AC%E4%BA%8C%E5%AD%A3%20%E7%AC%AC%E4%B8%80%E5%8D%B7%2000004.mpls%20m2ts%20%E6%97%B6%E9%97%B4.png)](https://sbx.mysmy.top/pictures/%E8%BD%AC%E7%94%9F%E4%B8%83%E7%8E%8B%E5%AD%90%20%E7%AC%AC%E4%BA%8C%E5%AD%A3%20%E7%AC%AC%E4%B8%80%E5%8D%B7%2000004.mpls%20m2ts%20%E6%97%B6%E9%97%B4.png)

## Example: a complete matching MPLS supplies another track

On *Re:Zero* season 3 volume 1, `00001.mpls` and the complete-timeline match `00002.mpls` each expose a PCM audio track. The application displays both in one **Edit tracks** dialog and identifies their source MPLS. Both can enter the same main output when their physical M2TS/PID relations do not overlap. The IGS row remains visible but disabled because Matroska cannot represent interactive graphics as an ordinary subtitle track.

[![Re:Zero season 3 volume 1 complete-MPLS track attachment](https://sbx.mysmy.top/pictures/Re%20Zero%20%E7%AC%AC%E4%B8%89%E9%9B%86%20%E7%AC%AC%E4%B8%80%E5%8D%B7%20%E6%95%B4%E6%9D%A1%20mpls%20%E9%99%84%E5%8A%A0.png)](https://sbx.mysmy.top/pictures/Re%20Zero%20%E7%AC%AC%E4%B8%89%E9%9B%86%20%E7%AC%AC%E4%B8%80%E5%8D%B7%20%E6%95%B4%E6%9D%A1%20mpls%20%E9%99%84%E5%8A%A0.png)

See [Blu-ray Disc Structure: SP tracks and MPLS-hidden tracks](Blu-ray-Disc-Structure.md#sp-tracks-and-mpls-hidden-tracks) for the complete rule.

## Suggested workflow

1. Choose the main MPLS from duration and playback results, not from its number alone.
2. Use **View chapters** to define the movie or episode output ranges.
3. Use **View M2TS time** to check duplicated clips, clip order, and `INTime`/`OUTTime`.
4. Confirm final video, audio, and subtitle choices in **Edit tracks**, and read the tooltip for any exceptional status.
5. Review the SP table last and uncheck duplicated, unwanted, or unnecessary standalone items.
