#!/usr/bin/env python3
"""Build 1080p MP4 presentation video from 13 slide PNGs and video/READING-SCRIPT-zh.md via edge-tts."""
import argparse
import asyncio
import json
import pathlib
import re
import subprocess
import sys

import edge_tts


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_MD = ROOT / "video" / "READING-SCRIPT-zh.md"
SLIDE_PNG_DIR = pathlib.Path("/mnt/data/hashtf-research/mfc-ap-2026/slides_png")
WORK_DIR = pathlib.Path("/mnt/data/hashtf-research/mfc-ap-2026/tts_work")
OUT_SRT = ROOT / "video" / "subtitles.srt"
OUT_MP4 = ROOT / "video" / "MFC-AP-Optimization-Video.mp4"


def parse_script_sections(md_path: pathlib.Path):
    txt = md_path.read_text(encoding="utf-8")
    sections = []
    cur_title = None
    buf = []
    for ln in txt.splitlines():
        m = re.match(r"^##\s+Slide\s+(\d+)\s*[:：]\s*(.+)$", ln.strip())
        if m:
            if cur_title is not None:
                sections.append((cur_title[0], cur_title[1], " ".join(buf).strip().replace("`", "")))
            cur_title = (int(m.group(1)), m.group(2).strip())
            buf = []
        elif cur_title is not None:
            s = ln.strip()
            if s and not s.startswith("<!--") and not s.startswith(">"):
                buf.append(s)
    if cur_title is not None:
        sections.append((cur_title[0], cur_title[1], " ".join(buf).strip().replace("`", "")))
    if not sections:
        raise ValueError(f"No `## Slide N: ...` sections found in {md_path}")
    return sections


def split_caption_phrases(text: str, max_chars: int = 24):
    # Split cleanly at punctuation, then wrap gracefully at whitespace / CJK boundaries without slicing ASCII words
    raw_clauses = [c.strip() for c in re.split(r"(?<=[。！？；，、])", text) if c.strip()]
    phrases = []
    cur = ""
    for cl in raw_clauses:
        if len(cur) + len(cl) <= max_chars:
            cur += cl
        else:
            if cur:
                phrases.append(cur)
            if len(cl) <= max_chars:
                cur = cl
            else:
                # Tokenize into ASCII words/paths vs single CJK chars so ASCII identifiers never split mid-token
                tokens = re.findall(r"[A-Za-z0-9_./+:-]+|\s+|.", cl)
                piece = ""
                for tok in tokens:
                    if not piece and tok.isspace():
                        continue
                    if len(piece) + len(tok) <= max_chars or not piece:
                        piece += tok
                    else:
                        phrases.append(piece.strip())
                        piece = "" if tok.isspace() else tok
                cur = piece.strip()
    if cur:
        phrases.append(cur)
    return phrases


def fmt_srt_ts(sec: float) -> str:
    ms_tot = max(0, int(round(sec * 1000)))
    h = ms_tot // 3600000
    m = (ms_tot % 3600000) // 60000
    s = (ms_tot % 60000) // 1000
    ms = ms_tot % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def synth_one_slide(idx: int, text: str, voice: str, rate: str, mp3_path: pathlib.Path):
    comm = edge_tts.Communicate(text, voice=voice, rate=rate)
    boundaries = []
    with mp3_path.open("wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                boundaries.append(
                    {
                        "offset": chunk["offset"] / 1e7,
                        "duration": chunk["duration"] / 1e7,
                        "text": chunk["text"],
                    }
                )
    return boundaries


def ffprobe_duration(media_path: pathlib.Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ]
    ).decode().strip()
    return float(out)


def run_cmd(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


async def build_all(voice: str, rate: str, pre_pad: float, post_pad: float, force: bool = False):
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    OUT_SRT.parent.mkdir(parents=True, exist_ok=True)

    sections = parse_script_sections(SCRIPT_MD)
    slide_pngs = sorted(SLIDE_PNG_DIR.glob("slide-*.png"))
    if not slide_pngs:
        slide_pngs = sorted(SLIDE_PNG_DIR.glob("*.png"))
    if len(slide_pngs) != len(sections):
        raise RuntimeError(f"Mismatch: {len(slide_pngs)} PNGs vs {len(sections)} script sections")

    wav_parts = []
    seg_videos = []
    srt_cues = []
    t_cursor = 0.0

    for (slide_num, title, text), png_path in zip(sections, slide_pngs):
        raw_mp3 = WORK_DIR / f"slide_{slide_num:02d}_raw.mp3"
        norm_wav = WORK_DIR / f"slide_{slide_num:02d}_norm.wav"
        seg_mp4 = WORK_DIR / f"slide_{slide_num:02d}.mp4"

        if not force and raw_mp3.exists() and raw_mp3.stat().st_size > 4096:
            print(f"Slide {slide_num:02d}: reusing cached {raw_mp3.name} ({raw_mp3.stat().st_size} B)")
        else:
            # Chunk by sentence (<130 chars) so Edge TTS endpoint reliably accepts every slide
            sents = [s.strip() for s in re.findall(r"[^。！？]+[。！？]?", text) if s.strip()]
            chunks = []
            cur_c = ""
            for s in sents:
                if len(cur_c) + len(s) <= 130:
                    cur_c += s
                else:
                    if cur_c:
                        chunks.append(cur_c)
                    cur_c = s
            if cur_c:
                chunks.append(cur_c)

            chunk_mp3s = []
            for ci, ch_txt in enumerate(chunks):
                ch_path = WORK_DIR / f"slide_{slide_num:02d}_c{ci:02d}.mp3"
                for attempt in range(15):
                    try:
                        await synth_one_slide(slide_num, ch_txt, voice, rate, ch_path)
                        if ch_path.exists() and ch_path.stat().st_size > 1024:
                            await asyncio.sleep(1.5)
                            break
                    except Exception as exc:
                        if ch_path.exists():
                            ch_path.unlink()
                        wait_s = min(15.0, 2.0 * (attempt + 1))
                        print(f"WARN slide {slide_num} chunk {ci} attempt {attempt+1} failed ({exc}); sleeping {wait_s:.0f}s", file=sys.stderr)
                        await asyncio.sleep(wait_s)
                if not ch_path.exists() or ch_path.stat().st_size == 0:
                    raise RuntimeError(f"Failed TTS synthesis for slide {slide_num} chunk {ci}")
                chunk_mp3s.append(ch_path)

            if len(chunk_mp3s) == 1:
                chunk_mp3s[0].replace(raw_mp3)
            else:
                clist = WORK_DIR / f"slide_{slide_num:02d}_chunks.txt"
                clist.write_text("\n".join(f"file '{p}'" for p in chunk_mp3s) + "\n")
                run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(clist), "-c", "copy", str(raw_mp3)])
        if not raw_mp3.exists() or raw_mp3.stat().st_size == 0:
            raise RuntimeError(f"Failed TTS synthesis for slide {slide_num}")

        raw_dur = ffprobe_duration(raw_mp3)
        delay_ms = int(round(pre_pad * 1000))
        # Pad pre + post silence cleanly, normalize speech level
        af = f"adelay={delay_ms}|{delay_ms},apad=pad_dur={post_pad:.3f},loudnorm=I=-16:TP=-1.5:LRA=11"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(raw_mp3),
                "-af",
                af,
                "-ar",
                "48000",
                "-ac",
                "2",
                str(norm_wav),
            ]
        )
        seg_dur = ffprobe_duration(norm_wav)
        wav_parts.append(norm_wav)

        # Build time-aligned caption cues within [t_cursor + pre_pad, t_cursor + pre_pad + raw_dur]
        phrases = split_caption_phrases(text, max_chars=26)
        tot_weight = sum(max(1, len(re.sub(r"[，。！？、；：（）() ]", "", p))) for p in phrases)
        cue_t = t_cursor + pre_pad
        for p in phrases:
            w = max(1, len(re.sub(r"[，。！？、；：（）() ]", "", p)))
            dt = raw_dur * (w / tot_weight)
            srt_cues.append((cue_t, cue_t + max(0.35, dt), p))
            cue_t += dt

        # Render silent normalized segment video at exact 1920x1080 24fps matching norm_wav duration
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-framerate",
                "24",
                "-i",
                str(png_path),
                "-t",
                f"{seg_dur:.6f}",
                "-vf",
                "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#ECEFF4,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-an",
                str(seg_mp4),
            ]
        )
        seg_videos.append(seg_mp4)
        t_cursor += seg_dur
        print(f"Slide {slide_num:02d} ({title}): speech={raw_dur:.2f}s seg={seg_dur:.2f}s cum={t_cursor:.2f}s")

    # Write SRT
    with OUT_SRT.open("w", encoding="utf-8") as f:
        for idx, (t0, t1, p) in enumerate(srt_cues, 1):
            f.write(f"{idx}\n{fmt_srt_ts(t0)} --> {fmt_srt_ts(t1)}\n{p}\n\n")

    # Concat audio + video
    vid_list = WORK_DIR / "vid_concat.txt"
    aud_list = WORK_DIR / "aud_concat.txt"
    vid_list.write_text("\n".join(f"file '{p}'" for p in seg_videos) + "\n")
    aud_list.write_text("\n".join(f"file '{p}'" for p in wav_parts) + "\n")

    merged_vid = WORK_DIR / "merged_silent.mp4"
    merged_aud = WORK_DIR / "merged_audio.wav"
    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(vid_list), "-c", "copy", str(merged_vid)])
    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(aud_list), "-c", "copy", str(merged_aud)])

    # Burn crisp Nord dark-pill subtitles + global loudnorm pass + AAC 192k
    srt_escaped = str(OUT_SRT).replace(":", r"\:")
    # Note libass uses &HAABBGGRR (00=opaque, FF=transparent): #2E3440 -> BGR 40342E at high opacity &H20
    sub_style = (
        "FontName=WenQuanYi Zen Hei,FontSize=13,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H2040342E,BackColour=&H2040342E,BorderStyle=4,Outline=2,Shadow=0,MarginV=12,Alignment=2"
    )
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(merged_vid),
            "-i",
            str(merged_aud),
            "-vf",
            f"subtitles='{srt_escaped}':force_style='{sub_style}'",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(OUT_MP4),
        ]
    )
    print(f"FINAL VIDEO -> {OUT_MP4} (total {ffprobe_duration(OUT_MP4):.2f}s)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--voice", default="zh-TW-YunJheNeural")
    p.add_argument("--rate", default="+10%")
    p.add_argument("--pre-pad", type=float, default=0.35)
    p.add_argument("--post-pad", type=float, default=0.55)
    p.add_argument("--force", action="store_true", help="Re-synthesize cached slide MP3s.")
    args = p.parse_args()
    asyncio.run(build_all(args.voice, args.rate, args.pre_pad, args.post_pad, force=args.force))


if __name__ == "__main__":
    main()
