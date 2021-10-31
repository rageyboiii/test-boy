import asyncio
import copy
import datetime
import json
import math
import os
import re
from json import dumps
from typing import List, Literal, Optional, Union

import aiohttp
import async_timeout
import nextcord as discord
import validators
import wavelink
from nextcord.ext import commands, menus
from numpy import random

from functions import MessageColors, MyContext, checks, config, embed

URL_REG = re.compile(r'https?://(?:www\.)?.+')


def can_play():
  async def predicate(ctx: MyContext) -> Optional[bool]:
    connect_perms = ["connect", "speak"]
    missing = []
    if ctx.author.voice is None or ctx.author.voice.channel is None:
      raise NoChannelProvided()
    for perm, value in ctx.author.voice.channel.permissions_for(ctx.me):
      if value is False and perm.lower() in connect_perms:
        missing.append(perm)
    if len(missing) > 0:
      raise commands.BotMissingPermissions(missing)
    return True
  return commands.check(predicate)


class NoChannelProvided(commands.CommandError):
  def __init__(self):
    super().__init__("You must be in a voice channel or provide one to connect to.")


class IncorrectChannelError(commands.CommandError):
  def __init__(self):
    super().__init__("You must be in the same voice channel as the bot.")


class NoCustomSoundsFound(commands.CommandError):
  def __init__(self):
    super().__init__("There are no custom sounds for this server (yet)")


class VoiceConnectionError(commands.CommandError):
  def __init__(self):
    super().__init__("An error occured while connecting to a voice channel.")


class Track(wavelink.Track):
  __slots__ = ("requester", "thumbnail",)

  def __init__(self, *args, **kwargs):
    super().__init__(*args)
    self.requester = kwargs.get("requester")
    self.thumbnail = kwargs.get("thumbnail")


class Player(wavelink.Player):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

    self.ctx: MyContext = kwargs.get("ctx", None)
    self.dj: Optional[discord.Member] = self.ctx.author if self.ctx else None

    self.queue = asyncio.Queue()

    self.waiting = False

    self.pause_votes = set()
    self.resume_votes = set()
    self.skip_votes = set()
    self.shuffle_votes = set()
    self.stop_votes = set()

  async def connect(self, channel: Union[discord.VoiceChannel, discord.StageChannel], self_deaf: bool = True) -> Union[discord.VoiceChannel, discord.StageChannel]:
    try:
      await self.ctx.guild.change_voice_state(channel=channel, self_deaf=self_deaf)
    except asyncio.TimeoutError:
      raise VoiceConnectionError(f"Connecting to channel: `{channel}` timed out.")

    return channel

  async def disconnect(self, *, force: bool = False):
    guild = self.bot.get_guild(self.guild_id)
    if not guild and force is True:
      self.channel_id = None
      return
    if not guild:
      raise wavelink.errors.InvalidIDProvided(f'No guild found for id <{self.guild_id}>')

    await self.ctx.guild.change_voice_state(channel=None)

  async def do_next(self):
    if self.is_playing or self.waiting:
      return

    self.pause_votes.clear()
    self.resume_votes.clear()
    self.skip_votes.clear()
    self.shuffle_votes.clear()
    self.stop_votes.clear()

    try:
      self.waiting = True
      with async_timeout.timeout(300):
        track = await self.queue.get()
    except asyncio.TimeoutError:
      # No music has been played for 5 minutes, cleanup and disconnect...
      return await self.teardown()

    await self.play(track)
    self.waiting = False

    await self.ctx.send(embed=self.build_embed())

  def build_embed(self) -> Optional[discord.Embed]:
    track = self.current
    if not track:
      return

    channel = self.bot.get_channel(int(self.channel_id))
    qsize = self.queue.qsize()

    try:
      duration = str(datetime.timedelta(milliseconds=int(track.length)))
    except OverflowError:
      duration = "??:??:??"

    return embed(
        title=f"Now playing: **{track.title}**",
        thumbnail=track.thumbnail,
        url=track.uri,
        fieldstitle=["Duration", "Queue Length", "Volume", "Requested By", "DJ", "Channel"],
        fieldsval=[duration, str(qsize), f"**`{self.volume}%`**", f"{track.requester.mention}", f"{self.dj.mention}", f"{channel.mention}"],
        color=MessageColors.MUSIC)

  async def teardown(self):
    try:
      await self.destroy()
    except KeyError:
      pass


class PaginatorSource(menus.ListPageSource):
  def __init__(self, entries: List[str], *, per_page: int = 10):
    super().__init__(entries, per_page=per_page)

  async def format_page(self, menu: menus.MenuPages, page: List[str]) -> discord.Embed:
    return embed(
        title="Coming up...",
        description='\n'.join(f'`{index}. {title}`' for index, title in enumerate(page, 1)),
        # fieldstitle=(f'`{index}. {title}`' for index, title in enumerate(page, 1)),
        color=MessageColors.MUSIC)

  def is_paginating(self) -> bool:
    return True


class QueueMenu(discord.ui.View, menus.MenuPages):
  def __init__(self, source, *, title="Commands", description="", delete_after=True):
    super().__init__(timeout=60.0)
    self._source = source
    self.current_page = 0
    self.ctx = None
    self.message = None
    self.delete_after = delete_after

  async def start(self, ctx, *, channel: discord.TextChannel = None, wait=False) -> None:
    await self._source._prepare_once()
    self.ctx = ctx
    self.buttons_to_disable()
    self.message = await self.send_initial_message(ctx, ctx.channel)

  async def send_initial_message(self, ctx: "MyContext", channel: discord.TextChannel):
    page = await self._source.get_page(0)
    kwargs = await self._get_kwargs_from_page(page)
    return await ctx.send(**kwargs)

  async def _get_kwargs_from_page(self, page):
    value = await super()._get_kwargs_from_page(page)
    if "view" not in value:
      value.update({"view": self})
    return value

  async def interaction_check(self, interaction: discord.Interaction) -> bool:
    if interaction.user and interaction.user == self.ctx.author:
      return True
    else:
      await interaction.response.send_message('This help menu is not for you.', ephemeral=True)
      return False

  async def on_timeout(self) -> None:
    self.stop()
    if self.delete_after and self.message:
      await self.message.delete()

  def buttons_to_disable(self, page: int = 0) -> None:
    if self._source.get_max_pages() == 1:
      self._first.disabled = True
      self._back.disabled = True
      self._last.disabled = True
      self._next.disabled = True
    elif page == 0:
      self._first.disabled = True
      self._back.disabled = True
      self._last.disabled = False
      self._next.disabled = False
    elif page == self._source.get_max_pages() - 1:
      self._first.disabled = False
      self._back.disabled = False
      self._last.disabled = True
      self._next.disabled = True
    else:
      self._first.disabled = False
      self._back.disabled = False
      self._last.disabled = False
      self._next.disabled = False

  @discord.ui.button(emoji="\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}\ufe0f", style=discord.ButtonStyle.primary, custom_id="queue-first")
  async def _first(self, button: discord.ui.Button, interaction: discord.Interaction):
    self.buttons_to_disable(0)
    await self.show_page(0)

  @discord.ui.button(emoji="\N{BLACK LEFT-POINTING TRIANGLE}\ufe0f", style=discord.ButtonStyle.primary, custom_id="queue-back")
  async def _back(self, button: discord.ui.Button, interaction: discord.Interaction):
    self.buttons_to_disable(self.current_page - 1)
    await self.show_checked_page(self.current_page - 1)

  @discord.ui.button(emoji="\N{BLACK RIGHT-POINTING TRIANGLE}\ufe0f", style=discord.ButtonStyle.primary, custom_id="queue-next")
  async def _next(self, button: discord.ui.Button, interaction: discord.Interaction):
    self.buttons_to_disable(self.current_page + 1)
    await self.show_checked_page(self.current_page + 1)

  @discord.ui.button(emoji="\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}\ufe0f", style=discord.ButtonStyle.primary, custom_id="queue-last")
  async def _last(self, button: discord.ui.Button, interaction: discord.Interaction):
    self.buttons_to_disable(self._source.get_max_pages() - 1)
    await self.show_page(self._source.get_max_pages() - 1)

  @discord.ui.button(emoji="\N{BLACK SQUARE FOR STOP}\ufe0f", style=discord.ButtonStyle.danger, custom_id="queue-stop")
  async def _stop(self, button: discord.ui.Button, interaction: discord.Interaction):
    self.stop()
    if self.delete_after:
      await self.message.delete(delay=0)


class Music(commands.Cog, wavelink.WavelinkMixin):
  """Listen to your favourite music and audio clips with Friday's music commands"""

  def __init__(self, bot):
    self.bot = bot

    if not hasattr(self.bot, "wavelink"):
      self.bot.wavelink = wavelink.Client(bot=bot, session=bot.session)

    bot.loop.create_task(self.start_nodes())

  async def start_nodes(self):
    await self.bot.wait_until_ready()

    if self.bot.wavelink.nodes:
      previous = self.bot.wavelink.nodes.copy()

      for node in previous.values():
        await node.destroy()

    nodes = {
        "MAIN": {
            "host": os.environ.get("LAVALINKUSHOST"),
            "port": os.environ.get("LAVALINKUSPORT"),
            "rest_uri": f"http://{os.environ.get('LAVALINKUSHOST')}:{os.environ.get('LAVALINKUSPORT')}/",
            "password": os.environ.get("LAVALINKUSPASS"),
            "identifier": "MAIN",
            "region": "us_central",
        },
        "GERMANY": {
            "host": os.environ.get("LAVALINKGRHOST"),
            "port": os.environ.get("LAVALINKGRPORT"),
            "rest_uri": f"http://{os.environ.get('LAVALINKGRHOST')}:{os.environ.get('LAVALINKGRPORT')}/",
            "password": os.environ.get("LAVALINKGRPASS"),
            "identifier": "GERMANY",
            "region": "germany",
        }
    }

    for n in nodes.values():
      await self.bot.wavelink.initiate_node(**n)

  def cog_check(self, ctx: MyContext) -> bool:
    if not ctx.guild:
      raise commands.NoPrivateMessage()

    return True

  async def cog_command_error(self, ctx: MyContext, error: Exception):
    if isinstance(error, IncorrectChannelError):
      return

    if isinstance(error, NoChannelProvided):
      return await ctx.send(embed=embed(title=error, color=MessageColors.ERROR))

    if isinstance(error, commands.BadLiteralArgument):
      return await ctx.send(embed=embed(title=f"`{error.param.name}` must be one of `{', '.join(error.literals)}.`", color=MessageColors.ERROR))

  @wavelink.WavelinkMixin.listener()
  async def on_node_ready(self, node: wavelink.Node):
    print(f"Node {node.identifier} is ready!")

  @wavelink.WavelinkMixin.listener('on_track_stuck')
  @wavelink.WavelinkMixin.listener('on_track_end')
  @wavelink.WavelinkMixin.listener('on_track_exception')
  async def on_player_stop(self, node: wavelink.Node, payload):
    await payload.player.do_next()

  @commands.Cog.listener()
  async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    # TODO: when moved to another voice channel, Friday will some times just stop playing music until !pause and !resume are executed
    if member == self.bot.user:
      if after.channel is not None and after.channel.type == discord.ChannelType.stage_voice:
        await member.edit(suppress=False)

    # if not player:
    player: Player = self.bot.wavelink.get_player(member.guild.id, cls=Player)

    if member.bot:
      return

    if not player.channel_id or not player.ctx:
      player.node.players.pop(member.guild.id)
      return

    channel = self.bot.get_channel(int(player.channel_id))

    if member == player.dj and after.channel is None:
      for m in channel.members:
        if m.bot:
          continue
        else:
          player.dj = m
          return
    elif after.channel == channel and player.dj not in channel.members:
      player.dj = member

  async def cog_before_invoke(self, ctx: MyContext):
    player: Player = self.bot.wavelink.get_player(ctx.guild.id, cls=Player, ctx=ctx)

    if player.ctx:
      if player.ctx.channel != ctx.channel:
        await ctx.send(embed=embed(title=f"You must be in `{player.ctx.channel}` for this session.", color=MessageColors.ERROR))
        raise IncorrectChannelError
    if ctx.command.name == "connect" and not player.ctx:
      return
    elif self.is_privileged(ctx):
      return

    if not player.channel_id:
      return

    channel = self.bot.get_channel(int(player.channel_id))
    if not channel:
      return

    if player.is_connected:
      if ctx.author not in channel.members:
        await ctx.send(embed=embed(title=f"{ctx.author.mention}, you must be in {channel.mention} to use voice commands."))
        raise IncorrectChannelError

  def required(self, ctx: MyContext):
    player: Player = self.bot.wavelink.get_player(ctx.guild.id, cls=Player, ctx=ctx)
    channel = self.bot.get_channel(int(player.channel_id))
    required = math.ceil((len(channel.members) - 1) / 2.5)

    if ctx.command.name == "stop":
      if len(channel.members) == 3:
        required = 2

    return required

  def is_privileged(self, ctx: MyContext):
    player: Player = self.bot.wavelink.get_player(ctx.guild.id, cls=Player, ctx=ctx)

    return player.dj == ctx.author or ctx.author.guild_permissions.kick_members

  @commands.command(name="connect", aliases=["join"], help="Join a voice channel")
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
  @can_play()
  async def connect(self, ctx: MyContext, *, channel: Optional[Union[discord.VoiceChannel, discord.StageChannel]] = None):
    """Connect to a voice channel."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if player.is_connected:
      return

    channel = getattr(ctx.author.voice, 'channel', channel)
    if channel is None:
      raise NoChannelProvided

    await player.connect(channel)

  @commands.command(name="play", aliases=["p", "add"], extras={"examples": ["https://youtu.be/dQw4w9WgXcQ"]}, usage="<url/title>", help="Follow this command with the title of a song to search for it or just paste the Youtube/SoundCloud url if the search gives and undesirable result")
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
  @can_play()
  async def play(self, ctx: MyContext, *, query: str):
    """Play or queue a song with the given query."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    await ctx.trigger_typing()
    if not player.is_connected:
      await ctx.invoke(self.connect)

    query = query.strip('<>')
    if not URL_REG.match(query):
      query = f'ytsearch:{query}'

    tracks = await self.bot.wavelink.get_tracks(query)
    if not tracks:
      return await ctx.send(embed=embed(title='No songs were found with that query. Please try again.', color=MessageColors.ERROR))

    if isinstance(tracks, wavelink.TrackPlaylist):
      for track in tracks.tracks:
        track = Track(track.id, track.info, thumbnail=track.thumb, requester=ctx.author)
        await player.queue.put(track)
      if player.is_playing or player.is_paused:
        await ctx.send(embed=embed(
            title=f"Added the playlist {tracks.data['playlistInfo']['name']}",
            description=f" with {len(tracks.tracks)} songs to the queue.",
            color=MessageColors.MUSIC))
    else:
      track = Track(tracks[0].id, tracks[0].info, thumbnail=tracks[0].thumb, requester=ctx.author)
      await player.queue.put(track)
      if player.is_playing or player.is_paused:
        await ctx.send(embed=embed(title=f"Added {track.title} to the Queue", color=MessageColors.MUSIC))

    if not player.is_playing:
      await player.do_next()

  @commands.command(name="pause")
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
  @can_play()
  async def pause(self, ctx: MyContext):
    """Pause the currently playing song."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if player.is_paused or not player.is_connected:
      return

    if self.is_privileged(ctx):
      await ctx.send(embed=embed(title='An admin or DJ has paused the player.', color=MessageColors.MUSIC))
      player.pause_votes.clear()

      return await player.set_pause(True)

    required = self.required(ctx)
    player.pause_votes.add(ctx.author)

    if len(player.pause_votes) >= required:
      await ctx.send(embed=embed(title='Vote to pause passed. Pausing player.', color=MessageColors.MUSIC))
      player.pause_votes.clear()
      await player.set_pause(True)
    else:
      await ctx.send(embed=embed(title=f'{ctx.author} has voted to pause the player.', color=MessageColors.MUSIC))

  @commands.command(name="resume")
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
  @can_play()
  async def resume(self, ctx: MyContext):
    """Resume a currently paused player."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if not player.is_paused or not player.is_connected:
      return

    if self.is_privileged(ctx):
      await ctx.send(embed=embed(title='An admin or DJ has resumed the player.', color=MessageColors.MUSIC))
      player.resume_votes.clear()

      return await player.set_pause(False)

    required = self.required(ctx)
    player.resume_votes.add(ctx.author)

    if len(player.resume_votes) >= required:
      await ctx.send(embed=embed(title='Vote to resume passed. Resuming player.', color=MessageColors.MUSIC))
      player.resume_votes.clear()
      await player.set_pause(False)
    else:
      await ctx.send(embed=embed(title=f'{ctx.author.mention} has voted to resume the player.', color=MessageColors.MUSIC))

  @commands.command(name="skip", help="Skips the current song")
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
  @can_play()
  async def skip(self, ctx: MyContext):
    """Skip the currently playing song."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if not player.is_connected:
      return

    if self.is_privileged(ctx):
      await ctx.send(embed=embed(title='An admin or DJ has skipped the song.', color=MessageColors.MUSIC))
      player.skip_votes.clear()

      return await player.stop()

    if ctx.author == player.current.requester:
      await ctx.send(embed=embed(title='The song requester has skipped the song.', color=MessageColors.MUSIC))
      player.skip_votes.clear()

      return await player.stop()

    required = self.required(ctx)
    player.skip_votes.add(ctx.author)

    if len(player.skip_votes) >= required:
      await ctx.send(embed=embed(title='Vote to skip passed. Skipping song.', color=MessageColors.MUSIC))
      player.skip_votes.clear()
      await player.stop()
    else:
      await ctx.send(embed=embed(title=f'{ctx.author.mention} has voted to skip the song.', color=MessageColors.MUSIC))

  @commands.command(name="stop", aliases=["disconnect"], help="Stops the currently playing music")
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
  # @can_play()
  async def stop(self, ctx: MyContext):
    """Stop the player and clear all internal states."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if not player.is_connected:
      return

    if self.is_privileged(ctx):
      await ctx.send(embed=embed(title='An admin or DJ has stopped the player.', color=MessageColors.MUSIC))
      return await player.teardown()

    required = self.required(ctx)
    player.stop_votes.add(ctx.author)

    if len(player.stop_votes) >= required:
      await ctx.send(embed=embed(title='Vote to stop passed. Stopping the player.', color=MessageColors.MUSIC))
      await player.teardown()
    else:
      await ctx.send(embed=embed(title=f'{ctx.author.mention} has voted to stop the player.', color=MessageColors.MUSIC))

  @commands.command(name="volume", aliases=['v', 'vol'])
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
  @can_play()
  async def volume(self, ctx: MyContext, *, vol: int):
    """Change the players volume, between 1 and 100."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if not player.is_connected:
      return

    if not self.is_privileged(ctx):
      return await ctx.send(embed=embed(title='Only the DJ or admins may change the volume.', color=MessageColors.MUSIC))

    if not 0 < vol < 101:
      return await ctx.send('Please enter a value between 1 and 100.')

    await player.set_volume(vol)
    await ctx.send(f'Set the volume to **{vol}**%')

  @commands.command(name="shuffle", aliases=['mix'])
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
  @can_play()
  async def shuffle(self, ctx: MyContext):
    """Shuffle the players queue."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if not player.is_connected:
      return

    if player.queue.qsize() < 3:
      return await ctx.send(embed=embed(title='Add more songs to the queue before shuffling.', color=MessageColors.MUSIC))

    if self.is_privileged(ctx):
      await ctx.send(embed=embed(title='An admin or DJ has shuffled the playlist.', color=MessageColors.MUSIC))
      player.shuffle_votes.clear()
      return random.shuffle(player.queue._queue)

    required = self.required(ctx)
    player.shuffle_votes.add(ctx.author)

    if len(player.shuffle_votes) >= required:
      await ctx.send(embed=embed(title='Vote to shuffle passed. Shuffling the playlist.', color=MessageColors.MUSIC))
      player.shuffle_votes.clear()
      random.shuffle(player.queue._queue)
    else:
      await ctx.send(embed=embed(title=f'{ctx.author.mention} has voted to shuffle the playlist.', color=MessageColors.MUSIC))

  @commands.command(name="equalizer", aliases=['eq'])
  @checks.is_min_tier(list(config.premium_tiers)[1])
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
  @can_play()
  async def equalizer(self, ctx: MyContext, *, equalizer: Literal["flat", "boost", "metal", "piano"]):
    """Change the players equalizer."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if not player.is_connected:
      return

    if not self.is_privileged(ctx):
      return await ctx.send(embed=embed(title='Only the DJ or admins may change the equalizer.', color=MessageColors.ERROR))

    eqs = {'flat': wavelink.Equalizer.flat(),
           'boost': wavelink.Equalizer.boost(),
           'metal': wavelink.Equalizer.metal(),
           'piano': wavelink.Equalizer.piano()}

    eq = eqs.get(equalizer.lower(), None)

    if not eq:
      joined = "\n".join(eqs.keys())
      return await ctx.send(embed=embed(title=f'Invalid EQ provided. Valid EQs:\n\n{joined}', color=MessageColors.ERROR))

    await ctx.send(embed=embed(title=f'Successfully changed equalizer to {equalizer}', color=MessageColors.MUSIC))
    await player.set_eq(eq)

  @commands.command(name="queue", aliases=['que'], help="shows the song queue")
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.channel, wait=True)
  @can_play()
  async def queue(self, ctx: MyContext):
    """Display the players queued songs."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if not player.is_connected:
      return

    if player.queue.qsize() == 0:
      return await ctx.send(embed=embed(title='There are no more songs in the queue.', color=MessageColors.ERROR))

    entries = [track.title for track in player.queue._queue]
    pages = PaginatorSource(entries=entries)
    paginator = QueueMenu(source=pages, delete_after=True)

    await paginator.start(ctx)

  @commands.command(name="nowplaying", aliases=['np', 'now_playing', 'current'])
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.channel, wait=True)
  @can_play()
  async def nowplaying(self, ctx: MyContext):
    """Update the player controller."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if not player.is_connected:
      return

    await ctx.send(embed=player.build_embed())
    # await player.invoke_controller()

  @commands.command(name="swap_dj", aliases=['swap'])
  @commands.guild_only()
  @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
  @can_play()
  async def swap_dj(self, ctx: MyContext, *, member: discord.Member = None):
    """Swap the current DJ to another member in the voice channel."""
    player: Player = self.bot.wavelink.get_player(guild_id=ctx.guild.id, cls=Player, ctx=ctx)

    if not player.is_connected:
      return

    if not self.is_privileged(ctx):
      return await ctx.send(embed=embed(title='Only admins and the DJ may use this command.', color=MessageColors.ERROR))

    members = self.bot.get_channel(int(player.channel_id)).members

    if member and member not in members:
      return await ctx.send(embed=embed(title=f'{member} is not currently in voice, so can not be a DJ.'))

    if member and member == player.dj:
      return await ctx.send(embed=embed(title='Cannot swap DJ to the current DJ... :)'))

    if len(members) <= 2:
      return await ctx.send(embed=embed(title='No more members to swap to.', color=MessageColors.MUSIC))

    if member:
      player.dj = member
      return await ctx.send(embed=embed(title=f'{member.mention} is now the DJ.', color=MessageColors.MUSIC))

    for m in members:
      if m == player.dj or m.bot:
        continue
      else:
        player.dj = m
        return await ctx.send(embed=embed(title=f'{member.mention} is now the DJ.', color=MessageColors.MUSIC))

  @commands.group(name="custom", aliases=["c"], invoke_without_command=True, help="Play sounds/songs without looking for the url everytime")
  @commands.guild_only()
  # @commands.cooldown(1,4, commands.BucketType.channel)
  @can_play()
  @commands.max_concurrency(1, commands.BucketType.channel, wait=True)
  async def custom(self, ctx, name: str):
    try:
      async with ctx.typing():
        sounds = await self.bot.db.query("SELECT customSounds FROM servers WHERE id=$1 LIMIT 1", str(ctx.guild.id))
        sounds = [json.loads(x) for x in sounds]
    except Exception:
      await ctx.reply(embed=embed(title=f"The custom sound `{name}` has not been set, please add it with `{ctx.prefix}custom|c add <name> <url>`", color=MessageColors.ERROR))
    else:
      i = next((index for (index, d) in enumerate(sounds) if d["name"] == name), None)
      if sounds is not None and i is not None:
        sound = sounds[i]
        await ctx.invoke(self.bot.get_command("play"), query=sound["url"])
      else:
        await ctx.reply(embed=embed(title=f"The sound `{name}` has not been added, please check the `custom list` command", color=MessageColors.ERROR))

  @custom.command(name="add")
  @commands.guild_only()
  @commands.has_guild_permissions(manage_channels=True)
  async def custom_add(self, ctx, name: str, url: str):
    url = url.strip("<>")
    valid = validators.url(url)
    if valid is not True:
      await ctx.reply(embed=embed(title=f"Failed to recognize the url `{url}`", color=MessageColors.ERROR))
      return

    if name in ["add", "change", "replace", "list", "remove", "del"]:
      await ctx.reply(embed=embed(title=f"`{name}`is not an acceptable name for a command as it is a sub-command of custom", color=MessageColors.ERROR))
      return

    async with ctx.typing():
      name: str = "".join(name.split(" ")).lower()
      sounds: list = (await self.bot.db.query("SELECT customSounds FROM servers WHERE id=$1 LIMIT 1", str(ctx.guild.id)))
      if sounds == "" or sounds is None:
        sounds = []
      if name in [json.loads(x)["name"] for x in sounds]:
        return await ctx.reply(embed=embed(title=f"`{name}` was already added, please choose another", color=MessageColors.ERROR))
      sounds.append(json.dumps({"name": name, "url": url}))
      await self.bot.db.query("UPDATE servers SET customSounds=$1::json[] WHERE id=$2::text", sounds, str(ctx.guild.id))
    await ctx.reply(embed=embed(title=f"I will now play `{url}` for the command `{ctx.prefix}{ctx.command.parent} {name}`"))

  @custom.command(name="list")
  @commands.guild_only()
  async def custom_list(self, ctx):
    async with ctx.typing():
      sounds = await self.bot.db.query("SELECT customSounds FROM servers WHERE id=$1 LIMIT 1", str(ctx.guild.id))
      if sounds is None:
        raise NoCustomSoundsFound("There are no custom sounds for this server (yet)")
      sounds = [json.loads(x) for x in sounds]
      result = ""
      for sound in sounds:
        result += f"```{sound['name']} -> {sound['url']}```"
      if result == "":
        result = "There are no custom sounds for this server (yet)"
    await ctx.reply(embed=embed(title="The list of custom sounds", description=result))

  @custom.command(name="change", aliases=["replace"])
  @commands.guild_only()
  @commands.has_guild_permissions(manage_channels=True)
  async def custom_change(self, ctx, name: str, url: str):
    try:
      async with ctx.typing():
        name = "".join(name.split(" ")).lower()
        sounds = await self.bot.db.query("SELECT customSounds FROM servers WHERE id=$1 LIMIT 1", str(ctx.guild.id))
        sounds = json.loads(sounds)
        old = sounds[name]
        sounds[name] = url
        await self.bot.db.query("UPDATE servers SET customSounds=$1 WHERE id=$2", json.dumps(sounds), str(ctx.guild.id))
    except KeyError:
      await ctx.reply(embed=embed(title=f"Could not find the custom command `{name}`", color=MessageColors.ERROR))
    else:
      await ctx.reply(embed=embed(title=f"Changed `{name}` from `{old}` to `{url}`"))

  @custom.command(name="remove", aliases=["del"])
  @commands.guild_only()
  @commands.has_guild_permissions(manage_channels=True)
  async def custom_del(self, ctx, name: str):
    try:
      async with ctx.typing():
        name = "".join(name.split(" ")).lower()
        sounds = await self.bot.db.query("SELECT customSounds FROM servers WHERE id=$1 LIMIT 1", str(ctx.guild.id))
        sounds = [json.loads(x) for x in sounds]
        sounds.pop(next((index for (index, d) in enumerate(sounds) if d["name"] == name), None))
        await self.bot.db.query("UPDATE servers SET customSounds=$1::json[] WHERE id=$2", [json.dumps(x) for x in sounds], str(ctx.guild.id))
    except KeyError:
      await ctx.reply(embed=embed(title=f"Could not find the custom command `{name}`", color=MessageColors.ERROR))
    else:
      await ctx.reply(embed=embed(title=f"Removed the custom sound `{name}`"))

  @custom.command(name="clear")
  @commands.guild_only()
  @commands.has_guild_permissions(manage_channels=True)
  async def custom_clear(self, ctx):
    async with ctx.typing():
      await self.bot.db.query("UPDATE servers SET customsounds=NULL WHERE id=$1", str(ctx.guild.id))
    await ctx.send(embed=embed(title="Cleared this servers custom commands"))


def setup(bot):
  bot.add_cog(Music(bot))
