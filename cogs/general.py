import asyncio
from typing import Optional

import nextcord as discord
from nextcord.ext import commands
from typing_extensions import TYPE_CHECKING

from functions import MyContext, config, embed, MessageColors, views

if TYPE_CHECKING:
  from index import Friday as Bot

GENERAL_CHANNEL_NAMES = {"welcome", "general", "lounge", "chat", "talk", "main"}


class General(commands.Cog):

  def __init__(self, bot: "Bot"):
    self.bot = bot

  def __repr__(self) -> str:
    return "<cogs.General>"

  def welcome_message(self, *, prefix: str = config.defaultPrefix) -> dict:
    friday_emoji = self.bot.get_emoji(833507598413201459) if self.bot.get_emoji(833507598413201459) is not None else ''
    return dict(embed=embed(
        title=f"{friday_emoji}Thank you for inviting me to your server{friday_emoji}",
        description=f"I will respond to messages when I am mentioned. To get started with commands type `{prefix}help` or `@{self.bot.user.name} help`.\n"
        f"If something goes terribly wrong and you want it to stop, talk to my creator with the command `{prefix}issue <message>`",
        thumbnail=self.bot.user.display_avatar.url,
        fieldstitle=["Prefix", "Setting a language", "Notice for chat system", "Chatbot intelligence"],
        fieldsval=[
            f"To change my prefix use the `{prefix}prefix` command.",
            f"If you want me to speak another language then use the `{prefix}lang <language>` command eg.`{prefix}lang spanish` or `{prefix}lang es`",
            "Chat message from Friday are not generated by a human, they are now generated by an AI, the only response from a human is the BOLDED sensitive content message",
            "__For Friday's chatbot system to be free by default the model used is not the smartest. To get access to smarter models please check out the patreon page.__"
        ],
        fieldsin=[False, False, False, False]
    ), view=views.Links())

  @commands.Cog.listener()
  async def on_guild_join(self, guild: discord.Guild):
    while self.bot.is_closed():
      await asyncio.sleep(0.1)
    priority_channels = []
    channels = []
    for channel in guild.text_channels:
      if channel == guild.system_channel or any(x in channel.name for x in GENERAL_CHANNEL_NAMES):
        priority_channels.append(channel)
      else:
        channels.append(channel)
    channels = priority_channels + channels
    try:
      channel = next(
          x
          for x in channels
          if isinstance(x, discord.TextChannel) and x.permissions_for(guild.me).send_messages
      )
    except StopIteration:
      return

    await channel.send(**self.welcome_message())

  @commands.command(name="prefix", extras={"examples": ["?", "f!"]}, help="Sets the prefix for Fridays commands")
  @commands.guild_only()
  @commands.has_guild_permissions(manage_guild=True)
  async def _prefix(self, ctx: "MyContext", new_prefix: Optional[str] = config.defaultPrefix):
    new_prefix = new_prefix.lower()
    if len(new_prefix) > 5:
      return await ctx.reply(embed=embed(title="Can't set a prefix with more than 5 characters", color=MessageColors.ERROR))
    await self.bot.db.query("UPDATE servers SET prefix=$1 WHERE id=$2", str(new_prefix), str(ctx.guild.id))
    self.bot.prefixes[ctx.guild.id] = new_prefix
    await ctx.reply(embed=embed(title=f"My new prefix is `{new_prefix}`"))

  @commands.command(name="intro", help="Replies with the intro message for the bot")
  async def norm_ping(self, ctx: "MyContext"):
    await ctx.send(**self.welcome_message())


def setup(bot):
  bot.add_cog(General(bot))