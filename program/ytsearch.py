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


from config import BOT_USERNAME
from driver.decorators import check_blacklist
from driver.filters import command
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from youtube_search import YoutubeSearch

from driver.utils import R


@Client.on_message(command(["search", f"search@{BOT_USERNAME}"]) & ~filters.edited)
@check_blacklist()
async def youtube_search(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(R("search_help"))
    query = message.text.split(None, 1)[1]
    m = await message.reply_text(f"🔍 **{R('loading')}**")
    results = YoutubeSearch(query, max_results=5).to_dict()
    text = ""
    for i in range(5):
        try:
            text += f"🏷 **{R('search_name')}** __{results[i]['title']}__\n"
            text += f"⏱ **{R('search_duration')}** `{results[i]['duration']}`\n"
            text += f"👀 **{R('search_views')}** `{results[i]['views']}`\n"
            text += f"📣 **{R('search_channel')}** {results[i]['channel']}\n"
            text += f"🔗 **{R('search_link')}** https://www.youtube.com{results[i]['url_suffix']}\n\n"
        except IndexError:
            break
    await m.edit_text(
        text,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"🗑 {R('close')}", callback_data="close_panel")]]
        ),
    )
