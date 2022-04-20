"""
Video + Music Stream Telegram Bot
Copyright (c) 2022-present levina=lab <https://github.com/levina-lab>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but without any warranty; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/licenses.html>
"""

import re
import asyncio

from pyrogram import Client
from pyrogram.errors import UserAlreadyParticipant, UserNotParticipant
from pyrogram.types import InlineKeyboardMarkup, Message

from pytgcalls import StreamType
from pytgcalls.types.input_stream import AudioPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio
from pytgcalls.exceptions import NoAudioSourceFound, NoActiveGroupCall, GroupCallNotFound

from program import LOGS
from program.utils.inline import stream_markup
from driver.design.thumbnail import thumb
from driver.design.chatname import CHAT_TITLE
from driver.filters import command, other_filters
from driver.queues import QUEUE, add_to_queue
from driver.core import calls, user, me_user
from driver.utils import bash, remove_if_exists, from_tg_get_msg, R
from driver.database.dbqueue import add_active_chat, remove_active_chat, music_on
from driver.decorators import require_admin, check_blacklist

from config import IMG_1, IMG_2, IMG_5
from asyncio import TimeoutError
from youtubesearchpython import VideosSearch


def ytsearch(query: str):
    try:
        search = VideosSearch(query, limit=1).result()
        data = search["result"][0]
        songname = data["title"]
        url = data["link"]
        duration = data["duration"]
        thumbnail = data["thumbnails"][0]["url"]
        return [songname, url, duration, thumbnail]
    except Exception as e:
        print(e)
        return 0


async def ytdl(link: str):
    stdout, stderr = await bash(
        f'yt-dlp --geo-bypass -g -f "[height<=?720][width<=?1280]" {link}'
    )
    if stdout:
        return 1, stdout
    return 0, stderr


def convert_seconds(seconds):
    seconds = seconds % (24 * 3600)
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    return "%02d:%02d" % (minutes, seconds)


async def stream_audio_file(c: Client, m: Message, replied: Message = None, link: str = None):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if link:
        try:
            replied = await from_tg_get_msg(link)
        except Exception as e:
            return await m.reply_text(f"🚫 {R('error')}\n\n» {e}")
    if not replied:
        return await m.reply_text(R("play_reply_file"))
    if replied.audio or replied.voice:
        if not link:
            suhu = await replied.reply(f"📥 {R('audio_download')}")
        else:
            suhu = await m.reply(f"📥 {R('audio_download')}")
        file = await replied.download()
        link = replied.link
        songname = R("music")
        thumbnail = f"{IMG_5}"
        duration = "00:00"
        try:
            if replied.audio:
                if replied.audio.title:
                    songname = replied.audio.title[:80]
                else:
                    songname = replied.audio.file_name[:80]
                if replied.audio.thumbs:
                    if not link:
                        thumbnail = await c.download_media(replied.audio.thumbs[0].file_id)
                    else:
                        thumbnail = await user.download_media(replied.audio.thumbs[0].file_id)
                duration = convert_seconds(replied.audio.duration)
            elif replied.voice:
                songname = R("voice_note")
                duration = convert_seconds(replied.voice.duration)
        except Exception:
            pass

        if not thumbnail:
            thumbnail = f"{IMG_5}"

        if chat_id in QUEUE:
            await suhu.edit(f"🔄 {R('queue_track')}")
            gcname = m.chat.title
            ctitle = await CHAT_TITLE(gcname)
            titles = songname
            userid = m.from_user.id
            images = await thumb(thumbnail, titles, userid, ctitle)
            tracks = add_to_queue(chat_id, songname, file, link, R("music"), 0)
            person = f"[{m.from_user.first_name}](tg://user?id={m.from_user.id})"
            button = stream_markup(user_id)
            await suhu.delete()
            await m.send_photo(
                chat_id,
                photo=images,
                reply_markup=InlineKeyboardMarkup(button),
                caption=(R("audio_add_track").format(tracks) + "\n\n" +
                         R("audio_play").format(songname, link, duration, person)),
            )
            remove_if_exists(images)
        else:
            try:
                await suhu.edit(f"🔄 {R('join_group_call')}")
                gcname = m.chat.title
                ctitle = await CHAT_TITLE(gcname)
                titles = songname
                userid = m.from_user.id
                images = await thumb(thumbnail, titles, userid, ctitle)
                person = f"[{m.from_user.first_name}](tg://user?id={m.from_user.id})"
                button = stream_markup(user_id)
                await music_on(chat_id)
                await add_active_chat(chat_id)
                await calls.join_group_call(
                    chat_id,
                    AudioPiped(
                        file,
                        HighQualityAudio(),
                    ),
                    stream_type=StreamType().pulse_stream,
                )
                add_to_queue(chat_id, songname, file, link, R("music"), 0)
                await suhu.delete()
                await m.send_photo(
                    chat_id,
                    photo=images,
                    reply_markup=InlineKeyboardMarkup(button),
                    caption=R("audio_play").format(songname, link, duration, person),
                )
                remove_if_exists(images)
            except (NoActiveGroupCall, GroupCallNotFound):
                await suhu.delete()
                await remove_active_chat(chat_id)
                await m.reply_text(R("group_no_vc"))
            except Exception as e:
                LOGS.info(e)
    else:
        await m.reply_text(R("play_reply_file"))


@Client.on_message(command(["play"]) & other_filters)
@check_blacklist()
@require_admin(permissions=["can_manage_voice_chats", "can_delete_messages", "can_invite_users"], self=True)
async def audio_stream(c: Client, m: Message):
    await m.delete()
    replied = m.reply_to_message
    chat_id = m.chat.id
    user_id = m.from_user.id
    if m.sender_chat:
        return await m.reply_text(R("play_no_anony"))
    try:
        ubot = me_user.id
        b = await c.get_chat_member(chat_id, ubot)
        if b.status == "banned":
            try:
                await m.reply_text(R("userbot_banned"))
                await remove_active_chat(chat_id)
            except Exception:
                pass
            invitelink = (await c.get_chat(chat_id)).invite_link
            if not invitelink:
                await c.export_chat_invite_link(chat_id)
                invitelink = (await c.get_chat(chat_id)).invite_link
            if invitelink.startswith("https://t.me/+"):
                invitelink = invitelink.replace(
                    "https://t.me/+", "https://t.me/joinchat/"
                )
            await user.join_chat(invitelink)
            await remove_active_chat(chat_id)
    except UserNotParticipant:
        try:
            invitelink = (await c.get_chat(chat_id)).invite_link
            if not invitelink:
                await c.export_chat_invite_link(chat_id)
                invitelink = (await c.get_chat(chat_id)).invite_link
            if invitelink.startswith("https://t.me/+"):
                invitelink = invitelink.replace(
                    "https://t.me/+", "https://t.me/joinchat/"
                )
            await user.join_chat(invitelink)
            await remove_active_chat(chat_id)
        except UserAlreadyParticipant:
            pass
        except Exception as e:
            return await m.reply_text(R("userbot_failed").format(e))
    if replied:
        if replied.audio or replied.voice:
            await stream_audio_file(c, m, replied)
        else:
            if len(m.command) < 2:
                await m.reply(R("play_reply_file"))
            else:
                suhu = await c.send_message(chat_id, f"🔍 **{R('loading')}**")
                query = m.text.split(None, 1)[1]
                search = ytsearch(query)
                if search == 0:
                    await suhu.edit(f"❌ **{R('search_no')}**")
                else:
                    songs = search[0]
                    title = search[0]
                    links = search[1]
                    durations = search[2]
                    thumbnail = search[3]
                    userid = m.from_user.id
                    gcname = m.chat.title
                    ctitle = await CHAT_TITLE(gcname)
                    images = await thumb(thumbnail, title, userid, ctitle)
                    person = f"[{m.from_user.first_name}](tg://user?id={m.from_user.id})"
                    button = stream_markup(user_id)
                    out, ytlink = await ytdl(links)
                    if out == 0:
                        await suhu.edit(f"❌ {R('yt_dl_issue')}\n\n» `{ytlink}`")
                    else:
                        if chat_id in QUEUE:
                            await suhu.edit(f"🔄 {R('queue_track')}")
                            pos = add_to_queue(
                                chat_id, songs, ytlink, links, R("music"), 0
                            )
                            await suhu.delete()
                            await m.send_photo(
                                chat_id,
                                photo=images,
                                reply_markup=InlineKeyboardMarkup(button),
                                caption=(R("audio_add_track").format(pos) + "\n\n" +
                                         R("audio_play").format(songs, links, durations, person)),
                            )
                            remove_if_exists(images)
                        else:
                            try:
                                await suhu.edit(f"🔄 {R('join_group_call')}")
                                await music_on(chat_id)
                                await add_active_chat(chat_id)
                                await calls.join_group_call(
                                    chat_id,
                                    AudioPiped(
                                        ytlink,
                                        HighQualityAudio(),
                                    ),
                                    stream_type=StreamType().local_stream,
                                )
                                add_to_queue(chat_id, songs, ytlink, links, R("music"), 0)
                                await suhu.delete()
                                await m.send_photo(
                                    chat_id,
                                    photo=images,
                                    reply_markup=InlineKeyboardMarkup(button),
                                    caption=R("audio_play").format(songs, links, durations, person),
                                )
                                remove_if_exists(images)
                            except (NoActiveGroupCall, GroupCallNotFound):
                                await suhu.delete()
                                await remove_active_chat(chat_id)
                                await m.reply_text(R("group_no_vc"))
                            except NoAudioSourceFound:
                                await suhu.delete()
                                await remove_active_chat(chat_id)
                                await m.reply_text(f"❌ {R('play_no_audio_source')}")
    else:
        if len(m.command) < 2:
            await m.reply(R("play_reply_file"))
        elif "t.me" in m.command[1]:
            for i in m.command[1:]:
                if "t.me" in i:
                    await stream_audio_file(c, m, link=i)
                continue
        else:
            suhu = await c.send_message(chat_id, f"🔍 **{R('loading')}**")
            query = m.text.split(None, 1)[1]
            search = ytsearch(query)
            if search == 0:
                await suhu.edit(f"❌ **{R('search_no')}**")
            else:
                songs = search[0]
                title = search[0]
                links = search[1]
                durations = search[2]
                thumbnail = search[3]
                userid = m.from_user.id
                gcname = m.chat.title
                ctitle = await CHAT_TITLE(gcname)
                images = await thumb(thumbnail, title, userid, ctitle)
                person = f"[{m.from_user.first_name}](tg://user?id={m.from_user.id})"
                button = stream_markup(user_id)
                out, ytlink = await ytdl(links)
                if out == 0:
                    await suhu.edit(f"❌ {R('yt_dl_issue')}\n\n» `{ytlink}`")
                else:
                    if chat_id in QUEUE:
                        await suhu.edit(f"🔄 {R('queue_track')}")
                        pos = add_to_queue(chat_id, songs, ytlink, links, R("music"), 0)
                        await suhu.delete()
                        await m.send_photo(
                            chat_id,
                            photo=images,
                            reply_markup=InlineKeyboardMarkup(button),
                            caption=(R("audio_add_track").format(pos) + "\n\n" +
                                     R("audio_play").format(songs, links, durations, person)),
                        )
                        remove_if_exists(images)
                    else:
                        try:
                            await suhu.edit(f"🔄 {R('join_group_call')}")
                            await music_on(chat_id)
                            await add_active_chat(chat_id)
                            await calls.join_group_call(
                                chat_id,
                                AudioPiped(
                                    ytlink,
                                    HighQualityAudio(),
                                ),
                                stream_type=StreamType().local_stream,
                            )
                            add_to_queue(chat_id, songs, ytlink, links, R("music"), 0)
                            await suhu.delete()
                            await m.send_photo(
                                chat_id,
                                photo=images,
                                reply_markup=InlineKeyboardMarkup(button),
                                caption=R("audio_play").format(songs, links, durations, person),
                            )
                            remove_if_exists(images)
                        except (NoActiveGroupCall, GroupCallNotFound):
                            await suhu.delete()
                            await remove_active_chat(chat_id)
                            await m.reply_text(R("group_no_vc"))
                        except NoAudioSourceFound:
                            await suhu.delete()
                            await remove_active_chat(chat_id)
                            await m.reply_text(R("play_no_audio_source"))


@Client.on_message(command(["stream"]) & other_filters)
@check_blacklist()
@require_admin(permissions=["can_manage_voice_chats", "can_delete_messages", "can_invite_users"], self=True)
async def live_music_stream(c: Client, m: Message):
    await m.delete()
    chat_id = m.chat.id
    user_id = m.from_user.id
    if m.sender_chat:
        return await m.reply_text(R("play_no_anony"))
    try:
        ubot = me_user.id
        b = await c.get_chat_member(chat_id, ubot)
        if b.status == "banned":
            try:
                await m.reply_text(R("userbot_banned"))
                await remove_active_chat(chat_id)
            except Exception:
                pass
            invitelink = (await c.get_chat(chat_id)).invite_link
            if not invitelink:
                await c.export_chat_invite_link(chat_id)
                invitelink = (await c.get_chat(chat_id)).invite_link
            if invitelink.startswith("https://t.me/+"):
                invitelink = invitelink.replace(
                    "https://t.me/+", "https://t.me/joinchat/"
                )
            await user.join_chat(invitelink)
            await remove_active_chat(chat_id)
    except UserNotParticipant:
        try:
            invitelink = (await c.get_chat(chat_id)).invite_link
            if not invitelink:
                await c.export_chat_invite_link(chat_id)
                invitelink = (await c.get_chat(chat_id)).invite_link
            if invitelink.startswith("https://t.me/+"):
                invitelink = invitelink.replace(
                    "https://t.me/+", "https://t.me/joinchat/"
                )
            await user.join_chat(invitelink)
            await remove_active_chat(chat_id)
        except UserAlreadyParticipant:
            pass
        except Exception as e:
            return await m.reply_text(R("userbot_failed").format(e))
    if len(m.command) < 2:
        await m.reply_text(f"» {R('stream_url')}")
    else:
        url = m.text.split(None, 1)[1]
        msg = await m.reply_text(f"🔍 **{R('loading')}**")
        regex = r"^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+"
        match = re.match(regex, url)
        if match:
            coda, data = await ytdl(url)
        else:
            data = url
            coda = 1
        if coda == 0:
            await msg.edit_text(f"❌ {R('yt_dl_issue')}\n\n» `{data}`")
        else:
            if "m3u8" in url:
                if chat_id in QUEUE:
                    await msg.edit_text(f"🔄 {R('queue_track')}")
                    tracks = add_to_queue(chat_id, "m3u8 audio", data, url, R("music"), 0)
                    person = f"[{m.from_user.first_name}](tg://user?id={m.from_user.id})"
                    button = stream_markup(user_id)
                    await msg.delete()
                    await m.send_photo(
                        chat_id,
                        photo=f"{IMG_1}",
                        reply_markup=InlineKeyboardMarkup(button),
                        caption=(R("audio_add_track").format(tracks) + "\n\n" +
                                 R("stream_play").format("m3u8 audio stream", url, person)),
                    )
                else:
                    try:
                        await msg.edit_text(f"🔄 {R('join_group_call')}")
                        await music_on(chat_id)
                        await add_active_chat(chat_id)
                        await calls.join_group_call(
                            chat_id,
                            AudioPiped(
                                data,
                                HighQualityAudio(),
                            ),
                            stream_type=StreamType().live_stream,
                        )
                        add_to_queue(chat_id, "m3u8 audio", data, url, R("music"), 0)
                        person = f"[{m.from_user.first_name}](tg://user?id={m.from_user.id})"
                        button = stream_markup(user_id)
                        await msg.delete()
                        await m.send_photo(
                            chat_id,
                            photo=f"{IMG_2}",
                            reply_markup=InlineKeyboardMarkup(button),
                            caption=R("stream_play").format("m3u8 audio stream", url, person),
                        )
                    except (NoActiveGroupCall, GroupCallNotFound):
                        await msg.delete()
                        await remove_active_chat(chat_id)
                        await m.reply_text(R("group_no_vc"))
                    except NoAudioSourceFound:
                        await msg.delete()
                        await remove_active_chat(chat_id)
                        await m.reply_text(R("play_no_audio_source"))
            else:
                search = ytsearch(url)
                titles = search[0]
                songnames = search[0]
                thumbnail = search[3]
                userid = m.from_user.id
                gcname = m.chat.title
                ctitle = await CHAT_TITLE(gcname)
                images = await thumb(thumbnail, titles, userid, ctitle)
                person = f"[{m.from_user.first_name}](tg://user?id={m.from_user.id})"
                button = stream_markup(user_id)
                if chat_id in QUEUE:
                    await msg.edit_text(f"🔄 {R('queue_track')}")
                    pos = add_to_queue(chat_id, songnames, data, url, R("music"), 0)
                    await msg.delete()
                    await m.send_photo(
                        chat_id,
                        photo=image,
                        reply_markup=InlineKeyboardMarkup(button),
                        caption=(R("audio_add_track").format(pos) + "\n\n" +
                                 R("stream_play").format(songnames, url, person)),
                    )
                    remove_if_exists(images)
                else:
                    try:
                        await msg.edit_text(f"🔄 {R('join_group_call')}")
                        await music_on(chat_id)
                        await add_active_chat(chat_id)
                        await calls.join_group_call(
                            chat_id,
                            AudioPiped(
                                data,
                                HighQualityAudio(),
                            ),
                            stream_type=StreamType().live_stream,
                        )
                        add_to_queue(chat_id, songnames, data, url, R("music"), 0)
                        await msg.delete()
                        await m.send_photo(
                            chat_id,
                            photo=image,
                            reply_markup=InlineKeyboardMarkup(button),
                            caption=R("stream_play").format(songnames, url, person),
                        )
                        remove_if_exists(images)
                    except (NoActiveGroupCall, GroupCallNotFound):
                        await msg.delete()
                        await remove_active_chat(chat_id)
                        await m.reply_text(R("group_no_vc"))
                    except NoAudioSourceFound:
                        await msg.delete()
                        await remove_active_chat(chat_id)
                        await m.reply_text(R("play_no_audio_source"))
                    except TimeoutError:
                        await msg.delete()
                        await remove_active_chat(chat_id)
                        await m.reply_text(R("process_cancel"))
