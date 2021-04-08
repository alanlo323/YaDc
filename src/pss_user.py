from datetime import datetime
import math
import os
from typing import Dict, List, Optional, Tuple, Union

from discord import Embed
from discord.ext.commands import Context
from discord.file import File
from PIL import Image, ImageDraw, ImageEnhance, ImageFont
import numpy as np

import emojis
import pss_assert
import pss_core as core
import pss_entity as entity
import pss_fleet as fleet
import pss_login as login
import pss_lookups as lookups
import pss_room as room
import pss_ship as ship
import pss_sprites as sprites
import pss_tournament as tourney
import pss_user as user
import settings
from typehints import EntitiesData, EntityInfo
import utils


# ---------- Constants ----------

INSPECT_SHIP_BASE_PATH = f'ShipService/InspectShip2'

LEAGUE_BASE_PATH = f'LeagueService/ListLeagues2?accessToken='
LEAGUE_INFO_DESCRIPTION_PROPERTY_NAME = 'LeagueName'
LEAGUE_INFO_KEY_NAME = 'LeagueId'
LEAGUE_INFOS_CACHE = []

POWER_BAR_COLOR = (55, 255, 142)

SEARCH_USERS_BASE_PATH = f'UserService/SearchUsers?searchString='

SHORT_NAME_FONT: ImageFont.ImageFont

USER_DESCRIPTION_PROPERTY_NAME = 'Name'
USER_KEY_NAME = 'Id'





# ---------- User info ----------

async def get_user_details_by_info(ctx: Context, user_info: EntityInfo, max_tourney_battle_attempts: int = None, retrieved_at: datetime = None, past_fleet_infos: EntitiesData = None, as_embed: bool = settings.USE_EMBEDS) -> Union[List[Embed], List[str]]:
    is_past_data = past_fleet_infos is not None and past_fleet_infos

    user_id = user_info[USER_KEY_NAME]
    retrieved_at = retrieved_at or utils.get_utc_now()
    tourney_running = tourney.is_tourney_running(utc_now=retrieved_at)
    if past_fleet_infos:
        ship_info = {}
        fleet_info = past_fleet_infos.get(user_info.get(fleet.FLEET_KEY_NAME))
        current_user_info = await __get_user_info_by_id(user_id)
        if current_user_info.get(USER_DESCRIPTION_PROPERTY_NAME) != user_info.get(USER_DESCRIPTION_PROPERTY_NAME):
            user_info['CurrentName'] = current_user_info.get(USER_DESCRIPTION_PROPERTY_NAME)
    else:
        _, ship_info = await ship.get_inspect_ship_for_user(user_id)
        fleet_info = await __get_fleet_info_by_user_info(user_info)

    is_in_tourney_fleet = fleet.is_tournament_fleet(fleet_info) and tourney_running
    user_details = __create_user_details_from_info(user_info, fleet_info, ship_info, max_tourney_battle_attempts=max_tourney_battle_attempts, retrieved_at=retrieved_at, is_past_data=is_past_data, is_in_tourney_fleet=is_in_tourney_fleet)

    if as_embed:
        return [(await user_details.get_details_as_embed(ctx, display_inline=False))]
    else:
        return (await user_details.get_details_as_text(entity.EntityDetailsType.LONG))


async def get_users_infos_by_name(user_name: str) -> List[EntityInfo]:
    pss_assert.valid_parameter_value(user_name, 'user_name', min_length=0)

    user_infos = list((await __get_users_data(user_name)).values())
    return user_infos


async def get_user_infos_from_tournament_data_by_name(user_name: str, users_data: EntitiesData) -> List[EntityInfo]:
    user_name_lower = user_name.lower()
    result = {user_id: user_info for (user_id, user_info) in users_data.items() if user_name_lower in user_info.get(user.USER_DESCRIPTION_PROPERTY_NAME, '').lower()}
    user_infos_current = await __get_users_data(user_name)
    if user_infos_current:
        for user_info in user_infos_current.values():
            user_id = user_info[user.USER_KEY_NAME]
            if user_id in users_data:
                user_info = await __get_user_info_by_id(user_id)
                if user_id not in result:
                    result[user_id] = users_data[user_id]
                if result[user_id][user.USER_DESCRIPTION_PROPERTY_NAME] != user_info[user.USER_DESCRIPTION_PROPERTY_NAME]:
                    result[user_id]['CurrentName'] = user_info[user.USER_DESCRIPTION_PROPERTY_NAME]
    else:
        for tournament_user_id, tournament_user_info in result.items():
            user_info = await __get_user_info_by_id(tournament_user_id)
            if result[tournament_user_id][user.USER_DESCRIPTION_PROPERTY_NAME] != user_info[user.USER_DESCRIPTION_PROPERTY_NAME]:
                result[tournament_user_id]['CurrentName'] = user_info[user.USER_DESCRIPTION_PROPERTY_NAME]
    return list(result.values())


async def get_user_ship_layout(ctx: Context, user_id: str, as_embed: bool = settings.USE_EMBEDS) -> Tuple[Union[List[Embed], List[str]], File]:
    ships_designs_data = await ship.ships_designs_retriever.get_data_dict3()
    rooms_designs_data = await room.rooms_designs_retriever.get_data_dict3()
    rooms_designs_sprites_data = await room.rooms_designs_sprites_retriever.get_data_dict3()
    inspect_ship_path = await __get_inspect_ship_path(user_id)
    ship_data_raw = await core.get_data_from_path(inspect_ship_path)
    raw_dict = utils.convert.raw_xml_to_dict(ship_data_raw, preserve_lists=False)
    user_info: entity.EntityInfo = raw_dict['ShipService']['InspectShip']['User']
    user_ship_info: entity.EntityInfo = raw_dict['ShipService']['InspectShip']['Ship']
    ship_design_info: entity.EntityInfo = ships_designs_data[user_ship_info.get('ShipDesignId')]
    rooms_designs_sprites_ids = {value.get('RoomDesignId'): value.get('SpriteId') for value in rooms_designs_sprites_data.values() if value.get('RaceId') == ship_design_info.get('RaceId')}
    file_path = await __get_ship_layout(str(ctx.message.id), user_ship_info, ship_design_info, rooms_designs_data, rooms_designs_sprites_ids)
    title = f'{user_info[user.USER_DESCRIPTION_PROPERTY_NAME]}'
    description = [
        f'Fleet: {user_info[fleet.FLEET_DESCRIPTION_PROPERTY_NAME]}'
        f'Trophies: {user_info["Trophy"]}'
        f'Lvl {ship_design_info["ShipLevel"]} - {ship_design_info["ShipDesignName"]}'
    ]
    attachment = File(file_path, filename='layout.png')
    if as_embed:
        colour = utils.discord.get_bot_member_colour(ctx.bot, ctx.guild)
        embed = utils.discord.create_embed(title=title, description='\n'.join(description), colour=colour)
        output = [embed]
    else:
        output = [f'**{title}**'] + description
    return output, file_path


async def __get_ship_layout(file_name_prefix: str, user_ship_info: entity.EntityInfo, ship_design_info: entity.EntityInfo, rooms_designs_data: entity.EntitiesData, rooms_designs_sprites_ids: Dict[str, str]) -> str:
    user_id = user_ship_info['UserId']

    brightness_value = float(user_ship_info.get('BrightnessValue', '0'))
    hue_value = float(user_ship_info.get('HueValue', '0'))
    saturation_value = float(user_ship_info.get('SaturationValue', '0'))

    interior_sprite_id = ship_design_info['InteriorSpriteId']
    interior_sprite = await sprites.load_sprite(interior_sprite_id)
    interior_sprite = sprites.enhance_sprite(interior_sprite, brightness=brightness_value, hue=hue_value, saturation=saturation_value)
    # get grid sprite
    interior_grid_sprite = await sprites.load_sprite_from_disk(interior_sprite_id, suffix='grids')
    if interior_grid_sprite == None:
        interior_grid_sprite = sprites.create_empty_sprite(interior_sprite.width, interior_sprite.height)
        interior_grid_draw: ImageDraw.ImageDraw = ImageDraw.Draw(interior_grid_sprite)
        ship_mask = ship_design_info['Mask']
        ship_height = int(ship_design_info['Rows'])
        ship_width = int(ship_design_info['Columns'])
        grid_mask = np.array([int(val) for val in ship_mask]).reshape((ship_height, ship_width))
        grids = np.where(grid_mask)
        for coordinates in list(zip(grids[1], grids[0])):
            shape = [
                coordinates[0] * sprites.TILE_SIZE,
                coordinates[1] * sprites.TILE_SIZE,
                (coordinates[0] + 1) * sprites.TILE_SIZE - 1,
                (coordinates[1] + 1) * sprites.TILE_SIZE - 1
            ]
            interior_grid_draw.rectangle(shape, fill=None, outline=(0, 0, 0), width=1)
        sprites.save_sprite(interior_grid_sprite, f'{interior_sprite_id}_grids')
    interior_sprite.paste(interior_grid_sprite, (0, 0), interior_grid_sprite)

    room_frame_sprite_id = ship_design_info.get('RoomFrameSpriteId')
    door_frame_left_sprite_id = ship_design_info.get('DoorFrameLeftSpriteId')
    door_frame_right_sprite_id = ship_design_info.get('DoorFrameRightSpriteId')

    rooms_sprites_cache = {}
    rooms_decorations_sprites_cache = {}
    for ship_room_info in user_ship_info['Rooms'].values():
        room_design_id = ship_room_info[room.ROOM_DESIGN_KEY_NAME]
        room_under_construction = 1 if ship_room_info.get('RoomStatus') == 'Upgrading' else 0

        room_sprite = rooms_sprites_cache.get(room_design_id, {}).get(room_under_construction)

        if not room_sprite:
            room_design_info = rooms_designs_data[room_design_id]
            room_size = (int(room_design_info['Columns']), int(room_design_info['Rows']))

            if room_size == (1, 1):
                room_decoration_sprite = None
            else:
                room_decoration_sprite = rooms_decorations_sprites_cache.get(room_frame_sprite_id, {}).get(door_frame_left_sprite_id, {}).get(room_size)
                if not room_decoration_sprite:
                    room_decoration_sprite = await sprites.load_sprite_from_disk(room_frame_sprite_id, suffix=f'{door_frame_left_sprite_id}_{door_frame_right_sprite_id}_{room_size[0]}x{room_size[1]}')
                    if not room_decoration_sprite:
                        room_decoration_sprite = await make_room_decoration_sprite(room_frame_sprite_id, door_frame_left_sprite_id, door_frame_right_sprite_id, room_size[0], room_size[1])
                        rooms_decorations_sprites_cache.setdefault(room_frame_sprite_id, {}).setdefault(door_frame_left_sprite_id, {}).setdefault(door_frame_right_sprite_id, {})[room_size] = room_decoration_sprite

            if room_under_construction:
                room_sprite_id = room_design_info['ConstructionSpriteId']
            else:
                if room_decoration_sprite:
                    room_sprite_id = room_design_info['ImageSpriteId']
                else:
                    room_sprite_id = rooms_designs_sprites_ids.get(room_design_id, room_design_info['ImageSpriteId'])

            room_sprite = await create_room_sprite(room_sprite_id, room_decoration_sprite, room_design_info, brightness_value, hue_value, saturation_value)
            rooms_sprites_cache.setdefault(room_design_id, {})[room_under_construction] = room_sprite
        interior_sprite.paste(room_sprite, (int(ship_room_info['Column']) * sprites.TILE_SIZE, int(ship_room_info['Row']) * sprites.TILE_SIZE))
    file_name = f'{file_name_prefix}_{user_id}_layout'
    file_path = sprites.save_sprite(interior_sprite, file_name)
    return file_path


async def create_room_sprite(room_sprite_id: str, room_decoration_sprite: Image.Image, room_design_info: entity.EntityInfo, brightness_value: float, hue_value: float, saturation_value: float) -> Image.Image:
    result = await sprites.load_sprite(room_sprite_id)
    room_sprite_draw: ImageDraw.ImageDraw = ImageDraw.Draw(result)
    if not room_decoration_sprite:
        result = sprites.enhance_sprite(result, brightness=brightness_value, hue=hue_value, saturation=saturation_value)
    else:
        room_decoration_sprite = sprites.enhance_sprite(room_decoration_sprite, brightness=brightness_value, hue=hue_value, saturation=saturation_value)
        result.paste(room_decoration_sprite, (0, 0), room_decoration_sprite)
        logo_sprite_id = room_design_info.get('LogoSpriteId')
        if entity.entity_property_has_value(logo_sprite_id):
            logo_sprite = await sprites.load_sprite(logo_sprite_id)
            result.paste(logo_sprite, (1, 2), logo_sprite)
        power_bars_count = None
        max_system_power = room_design_info.get('MaxSystemPower')
        if entity.entity_property_has_value(max_system_power):
            power_bars_count = int(max_system_power) or None
        else:
            max_power_generated = room_design_info.get('MaxPowerGenerated')
            if entity.entity_property_has_value(max_power_generated):
                power_bars_count = int(max_power_generated) or None
        if power_bars_count:
            draw_power_bars(result, power_bars_count)

        room_short_name = room_design_info.get('RoomShortName')
        if entity.entity_property_has_value(room_short_name):
            short_name_x = 12
            short_name_y = 0
            room_sprite_draw.text((short_name_x, short_name_y), room_short_name, fill=(255, 255, 255), font=SHORT_NAME_FONT)
    return result


def fit_door_frame_to_room_height(door_frame_sprite: Image.Image, room_height: int) -> Image.Image:
    first_row = door_frame_sprite.crop((0, 0, door_frame_sprite.width, 1))
    top_part = first_row.resize((door_frame_sprite.width, (room_height - 2) * sprites.TILE_SIZE))

    result = sprites.create_empty_sprite(door_frame_sprite.width, door_frame_sprite.height + top_part.height)
    result.paste(top_part, (0, 0))
    result.paste(door_frame_sprite, (0, top_part.height), door_frame_sprite)
    return result


async def make_door_frame_sprite(door_frame_left_sprite_id: str, door_frame_right_sprite_id: str, room_height: int) -> Image.Image:
    door_frame_left_sprite = await sprites.load_sprite(door_frame_left_sprite_id)
    door_frame_right_sprite = await sprites.load_sprite(door_frame_right_sprite_id)
    width = door_frame_left_sprite.width + door_frame_right_sprite.width - 2

    result = sprites.create_empty_sprite(width, door_frame_left_sprite.height)
    result.paste(door_frame_right_sprite, (2, 0), door_frame_right_sprite)
    result.paste(door_frame_left_sprite, (0, 0), door_frame_left_sprite)

    if room_height > 2:
        result = fit_door_frame_to_room_height(result, room_height)
    sprites.save_sprite(result, f'door_frame_{door_frame_left_sprite_id}_{door_frame_right_sprite_id}_{room_height}')
    return result


async def make_room_decoration_sprite(room_frame_sprite_id: str, door_frame_left_sprite_id: str, door_frame_right_sprite_id: str, room_width: int, room_height: int) -> Image.Image:
    if room_width == 3 and room_height == 2:
        room_frame_sprite = await sprites.load_sprite(room_frame_sprite_id)
    else: # edit frame sprite
        room_frame_sprite = await sprites.load_sprite_from_disk(room_frame_sprite_id, suffix=f'{room_width}x{room_height}')
        if not room_frame_sprite:
            room_frame_sprite = await make_room_frame_sprite(room_frame_sprite_id, room_width, room_height)

    door_frame_sprite = await sprites.load_sprite_from_disk(door_frame_left_sprite_id, prefix='door_frame', suffix=f'{door_frame_right_sprite_id}_{room_height}')
    if not door_frame_sprite:
        door_frame_sprite = await make_door_frame_sprite(door_frame_left_sprite_id, door_frame_right_sprite_id, room_height)

    room_decoration_sprite = room_frame_sprite.copy()
    door_frame_y = room_frame_sprite.height - door_frame_sprite.height - 1
    room_decoration_sprite.paste(door_frame_sprite, (1, door_frame_y), door_frame_sprite)
    room_decoration_sprite.paste(room_frame_sprite, (0, 0), room_frame_sprite)

    sprites.save_sprite(room_decoration_sprite, f'{room_frame_sprite_id}_{door_frame_left_sprite_id}_{door_frame_right_sprite_id}_{room_width}x{room_height}')
    return room_decoration_sprite


async def make_room_frame_sprite(room_frame_sprite_id: str, room_width: int, room_height: int) -> Image.Image:
    room_frame_sprite = await sprites.load_sprite(room_frame_sprite_id)
    result = sprites.create_empty_room_sprite(room_width, room_height)
    from_left = sprites.TILE_SIZE // 2 # 12
    from_right = sprites.TILE_SIZE - from_left # 13

    upper_left_region_sprite = room_frame_sprite.crop((
        0,
        0,
        from_left,
        from_left
    ))
    upper_right_region_sprite = room_frame_sprite.crop((
        room_frame_sprite.width - from_right,
        0,
        room_frame_sprite.width,
        from_left
    ))
    bottom_left_region_sprite = room_frame_sprite.crop((
        0,
        room_frame_sprite.height - from_right,
        from_left,
        room_frame_sprite.height
    ))
    bottom_right_region_sprite = room_frame_sprite.crop((
        room_frame_sprite.width - from_right,
        room_frame_sprite.height - from_right,
        room_frame_sprite.width,
        room_frame_sprite.height
    ))

    top_center_region_sprite = room_frame_sprite.crop((
        from_left + 1,
        0,
        from_left + 1 + sprites.TILE_SIZE,
        from_left
    ))
    bottom_center_region_sprite = room_frame_sprite.crop((
        from_left + 1,
        room_frame_sprite.height - from_right,
        from_left + 1 + sprites.TILE_SIZE,
        room_frame_sprite.height
    ))
    left_center_region_sprite = room_frame_sprite.crop((
        0,
        from_left + 1,
        from_left,
        from_left + 1 + sprites.TILE_SIZE
    ))
    right_center_region_sprite = room_frame_sprite.crop((
        room_frame_sprite.width - from_right,
        from_left + 1,
        room_frame_sprite.width,
        from_left + 1 + sprites.TILE_SIZE
    ))

    result.paste(upper_left_region_sprite, (0, 0), upper_left_region_sprite)
    result.paste(upper_right_region_sprite, (result.width - from_left - 1, 0), upper_right_region_sprite)
    result.paste(bottom_left_region_sprite, (0, result.height - from_left - 1), bottom_left_region_sprite)
    result.paste(bottom_right_region_sprite, (result.width - from_left - 1, result.height - from_left - 1), bottom_right_region_sprite)
    for x in range(1, room_width):
        result.paste(top_center_region_sprite, (
            from_left + (x - 1) * sprites.TILE_SIZE,
            0
        ), top_center_region_sprite)
        result.paste(bottom_center_region_sprite, (
            from_left + (x - 1) * sprites.TILE_SIZE,
            result.height - from_right
        ), bottom_center_region_sprite)
    for y in range(1, room_height):
        result.paste(left_center_region_sprite, (
            0,
            from_left + (y - 1) * sprites.TILE_SIZE
        ))
        result.paste(right_center_region_sprite, (
            result.width - from_right,
            from_left + (y - 1) * sprites.TILE_SIZE
        ))
    return result


def draw_power_bars(room_sprite: Image.Image, power_count: int) -> None:
    room_sprite_draw = ImageDraw.Draw(room_sprite)
    power_bar_x_start = room_sprite.width - sprites.POWER_BAR_WIDTH - 1
    power_bar_y_end = sprites.POWER_BAR_Y_START + sprites.POWER_BAR_HEIGHT - 1
    for _ in range(power_count):
        power_bar_x_end = power_bar_x_start + sprites.POWER_BAR_WIDTH - 2
        coordinates = [power_bar_x_start, sprites.POWER_BAR_Y_START, power_bar_x_end, power_bar_y_end]
        room_sprite_draw.rectangle(coordinates, POWER_BAR_COLOR, POWER_BAR_COLOR)
        power_bar_x_start -= sprites.POWER_BAR_WIDTH + sprites.POWER_BAR_SPACING - 1


def get_user_search_details(user_info: EntityInfo) -> str:
    user_name = __get_user_name(user_info)
    user_trophies = user_info.get('Trophy', '?')
    user_stars = int(user_info.get('AllianceScore', '0'))

    details = []
    if user_info.get(fleet.FLEET_KEY_NAME, '0') != '0':
        fleet_name = user_info.get(fleet.FLEET_DESCRIPTION_PROPERTY_NAME, None)
        if fleet_name is not None:
            details.append(f'({fleet_name})')

    details.append(f'{emojis.trophy} {user_trophies}')
    if user_stars > 0:
        details.append(f'{emojis.star} {user_stars}')
    result = f'{user_name} ' + ' '.join(details)
    return result


async def __get_users_data(user_name: str) -> EntitiesData:
    path = f'{SEARCH_USERS_BASE_PATH}{utils.convert.url_escape(user_name)}'
    user_data_raw = await core.get_data_from_path(path)
    user_infos = utils.convert.xmltree_to_dict3(user_data_raw)
    return user_infos





# ---------- Transformation functions ----------

def __get_crew_borrowed(user_info: EntityInfo, fleet_info: EntityInfo = None, **kwargs) -> Optional[str]:
    result = None
    if fleet_info:
        result = user_info.get('CrewReceived')
    return result


def __get_crew_donated(user_info: EntityInfo, fleet_info: EntityInfo = None, **kwargs) -> Optional[str]:
    result = None
    if fleet_info:
        result = user_info.get('CrewDonated')
    return result


def __get_crew_donated_borrowed(user_info: EntityInfo, fleet_info: EntityInfo = None, **kwargs) -> Optional[str]:
    result = None
    if fleet_info:
        crew_donated = __get_crew_donated(user_info, fleet_info, **kwargs)
        crew_borrowed = __get_crew_borrowed(user_info, fleet_info, **kwargs)
        if crew_donated and crew_borrowed:
            result = f'{crew_donated}/{crew_borrowed}'
    return result


def __get_division_name(user_info: EntityInfo, fleet_info: EntityInfo = None, **kwargs) -> Optional[str]:
    result = fleet.get_division_name(fleet_info)
    return result


def __get_fleet_joined_at(user_info: EntityInfo, fleet_info: EntityInfo = None, retrieved_at: datetime = None, **kwargs) -> Optional[str]:
    result = None
    if fleet_info and retrieved_at:
        result = __get_timestamp(user_info, retrieved_at, **kwargs)
    return result


def __get_fleet_name_and_rank(user_info: EntityInfo, fleet_info: EntityInfo = None, **kwargs) -> Optional[str]:
    result = None
    if fleet_info:
        fleet_name = fleet_info.get(fleet.FLEET_DESCRIPTION_PROPERTY_NAME, '')
        fleet_membership = user_info.get('AllianceMembership')
        fleet_rank = None
        if fleet_membership:
            fleet_rank = lookups.get_lookup_value_or_default(lookups.ALLIANCE_MEMBERSHIP, fleet_membership, default=fleet_membership)
        if fleet_name:
            result = fleet_name
            if fleet_rank:
                result += f' ({fleet_rank})'
        else:
            result = '<data error>'
    else:
        result = '<no fleet>'
    return result


def __get_historic_data_note(user_info: EntityInfo, retrieved_at: datetime = None, is_past_data: bool = None, **kwargs) -> Optional[str]:
    if is_past_data:
        result = utils.datetime.get_historic_data_note(retrieved_at)
    else:
        result = None
    return result


def __get_league(user_info: EntityInfo, **kwargs) -> Optional[str]:
    result = None
    trophies = user_info.get('Trophy')
    if trophies is not None:
        result = f'{__get_league_from_trophies(int(trophies))}'
        highest_trophies = user_info.get('HighestTrophy')
        if highest_trophies is not None:
            result += f' (highest: {__get_league_from_trophies(int(highest_trophies))})'
    return result


async def __get_level(user_info: EntityInfo, ship_info: EntityInfo = None, **kwargs) -> Optional[str]:
    result = await ship.get_ship_level(ship_info)
    return result


def __get_pvp_attack_stats(user_info: EntityInfo, **kwargs) -> Optional[str]:
    result = None
    if all([field in user_info for field in ['PVPAttackDraws', 'PVPAttackLosses', 'PVPAttackWins']]):
        pvp_draws = int(user_info['PVPAttackDraws'])
        pvp_losses = int(user_info['PVPAttackLosses'])
        pvp_wins = int(user_info['PVPAttackWins'])
        result = __format_pvp_stats(pvp_wins, pvp_losses, pvp_draws)
    return result


def __get_pvp_defense_stats(user_info: EntityInfo, **kwargs) -> Optional[str]:
    result = None
    if all([field in user_info for field in ['PVPDefenceDraws', 'PVPDefenceLosses', 'PVPDefenceWins']]):
        defense_draws = int(user_info['PVPDefenceDraws'])
        defense_losses = int(user_info['PVPDefenceLosses'])
        defense_wins = int(user_info['PVPDefenceWins'])
        result = __format_pvp_stats(defense_wins, defense_losses, defense_draws)
    return result


def __get_star_value(user_info: EntityInfo, max_tourney_battle_attempts: int = None, retrieved_at: datetime = None, is_in_tourney_fleet: bool = None, **kwargs) -> Optional[str]:
    result = None
    if is_in_tourney_fleet:
        result = str(get_star_value_from_user_info(user_info))
    return result


def __get_stars(user_info: EntityInfo, max_tourney_battle_attempts: int = None, retrieved_at: datetime = None, is_in_tourney_fleet: bool = None, **kwargs) -> Optional[str]:
    attempts = __get_tourney_battle_attempts(user_info, retrieved_at)
    if attempts is not None and max_tourney_battle_attempts:
        attempts_left = max_tourney_battle_attempts - int(attempts)
    else:
        attempts_left = None

    result = None
    stars = user_info.get('AllianceScore')
    if is_in_tourney_fleet or (stars is not None and stars != '0'):
        result = stars
        if attempts_left is not None and is_in_tourney_fleet:
            result += f' ({attempts_left} attempts left)'
    return result


def __get_timestamp(user_info: EntityInfo, retrieved_at: datetime = None, **kwargs) -> Optional[str]:
    value = kwargs.get('entity_property')
    timestamp = utils.parse.pss_datetime(value)
    if timestamp is None:
        return None
    return __format_past_timestamp(timestamp, retrieved_at)


def __get_trophies(user_info: EntityInfo, **kwargs) -> Optional[str]:
    result = None
    trophies = user_info.get('Trophy')
    if trophies is not None:
        result = f'{trophies}'
        highest_trophies = user_info.get('HighestTrophy')
        if highest_trophies is not None:
            result += f' (highest: {highest_trophies})'
    return result


def __get_user_type(user_info: EntityInfo, **kwargs) -> Optional[str]:
    result = None
    user_type = user_info.get('UserType')
    if user_type is not None:
        result = lookups.get_lookup_value_or_default(lookups.USER_TYPE, user_type)
    return result


def __get_user_name(user_info: EntityInfo, **kwargs) -> Optional[str]:
    result = None
    user_name = user_info.get('Name')
    if user_name is not None:
        result = user_name
        current_user_name = user_info.get('CurrentName')
        if current_user_name is not None:
            result += f' (now: {current_user_name})'
    return result





# ---------- Helper functions ----------

def get_star_value_from_user_info(user_info: EntityInfo) -> Optional[int]:
    result = None
    trophies = user_info.get('Trophy')
    if trophies:
        trophies = int(trophies)
        stars = user_info.get('AllianceScore')
        if stars:
            stars = int(stars)
        else:
            stars = 0
        result = math.floor(max(trophies/1000, stars*0.15))
    return result


def __calculate_win_rate(wins: int, losses: int, draws: int) -> float:
    battles = wins + losses + draws
    if battles > 0:
        result = (wins + .5 * draws) / battles
        result *= 100
    else:
        result = 0.0
    return result


def __format_past_timestamp(timestamp: datetime, retrieved_at: datetime) -> str:
    retrieved_ago = utils.format.timedelta(timestamp - retrieved_at, include_seconds=False)
    result = f'{utils.format.datetime_for_excel(timestamp, include_seconds=False)} ({retrieved_ago})'
    return result


def __format_pvp_stats(wins: int, losses: int, draws: int) -> str:
    win_rate = __calculate_win_rate(wins, losses, draws)
    result = f'{wins}/{losses}/{draws} ({win_rate:0.2f}%)'
    return result


async def __get_fleet_info_by_user_info(user_info: EntityInfo) -> EntityInfo:
    result = {}
    fleet_id = user_info.get('AllianceId', '0')
    if fleet_id != '0':
        result = await fleet.get_fleets_data_by_id(fleet_id)
    return result


async def __get_inspect_ship_path(user_id: int) -> str:
    access_token = await login.DEVICES.get_access_token()
    result = f'{INSPECT_SHIP_BASE_PATH}?userId={user_id}&accessToken={access_token}'
    return result


def __get_league_from_trophies(trophies: int) -> str:
    result = '-'
    if trophies is not None:
        for league_info in LEAGUE_INFOS_CACHE:
            if trophies >= league_info['MinTrophy'] and trophies <= league_info['MaxTrophy']:
                result = league_info[LEAGUE_INFO_DESCRIPTION_PROPERTY_NAME]
                break
    return result


def __get_tourney_battle_attempts(user_info: EntityInfo, utc_now: datetime) -> int:
    attempts = user_info.get('TournamentBonusScore')
    if attempts:
        attempts = int(attempts)
        last_login_date = utils.parse.pss_datetime(user_info.get('LastLoginDate'))
        if last_login_date:
            if last_login_date.day != utc_now.day:
                attempts = 0
    return attempts


async def __get_user_info_by_id(user_id: int) -> EntityInfo:
    path = await __get_inspect_ship_path(user_id)
    inspect_ship_info_raw = await core.get_data_from_path(path)
    inspect_ship_info = utils.convert.raw_xml_to_dict(inspect_ship_info_raw)
    result = inspect_ship_info['ShipService']['InspectShip']['User']
    return result


def __parse_timestamp(user_info: EntityInfo, field_name: str) -> Optional[str]:
    result = None
    timestamp = user_info.get(field_name)
    if timestamp is not None:
        result = utils.parse.pss_datetime(timestamp)
    return result





# ---------- Create entity.EntityDetails ----------

def __create_user_details_from_info(user_info: EntityInfo, fleet_info: EntityInfo = None, ship_info: EntityInfo = None, max_tourney_battle_attempts: int = None, retrieved_at: datetime = None, is_past_data: bool = None, is_in_tourney_fleet: bool = None) -> entity.EscapedEntityDetails:
    return entity.EscapedEntityDetails(user_info, __properties['title'], None, __properties['properties'], __properties['embed_settings'], fleet_info=fleet_info, ship_info=ship_info, max_tourney_battle_attempts=max_tourney_battle_attempts, retrieved_at=retrieved_at, is_past_data=is_past_data, is_in_tourney_fleet=is_in_tourney_fleet)





# ---------- Initialization ----------

__properties: entity.EntityDetailsCreationPropertiesCollection = {
    'title': entity.EntityDetailPropertyCollection(
        entity.EntityDetailProperty('Title', False, omit_if_none=False, transform_function=__get_user_name)
    ),
    'properties': entity.EntityDetailPropertyListCollection(
        [
        entity.EntityDetailProperty('Account created', True, entity_property_name='CreationDate', transform_function=__get_timestamp),
        entity.EntityDetailProperty('Last Login', True, entity_property_name='LastLoginDate', transform_function=__get_timestamp),
        entity.EntityDetailProperty('Fleet', True, transform_function=__get_fleet_name_and_rank),
        entity.EntityDetailProperty('Division', True, transform_function=__get_division_name),
        entity.EntityDetailProperty('Joined fleet', True, entity_property_name='AllianceJoinDate', transform_function=__get_fleet_joined_at),
        entity.EntityDetailProperty('Trophies', True, transform_function=__get_trophies),
        entity.EntityDetailProperty('League', True, transform_function=__get_league),
        entity.EntityDetailProperty('Stars', True, transform_function=__get_stars),
        entity.EntityDetailProperty('Star value', True, transform_function=__get_star_value),
        entity.EntityDetailProperty('Crew donated', True, transform_function=__get_crew_donated, text_only=True),
        entity.EntityDetailProperty('Crew borrowed', True, transform_function=__get_crew_borrowed, text_only=True),
        entity.EntityDetailProperty('Crew donated/borrowed', True, transform_function=__get_crew_donated_borrowed, embed_only=True),
        entity.EntityDetailProperty('PVP win/lose/draw', True, transform_function=__get_pvp_attack_stats),
        entity.EntityDetailProperty('Defense win/lose/draw', True, transform_function=__get_pvp_defense_stats),
        entity.EntityDetailProperty('Level', True, transform_function=__get_level),
        entity.EntityDetailProperty('Championship score', True, entity_property_name='ChampionshipScore'),
        entity.EntityDetailProperty('User type', True, transform_function=__get_user_type),
        entity.EntityDetailProperty('history_note', False, transform_function=__get_historic_data_note, text_only=True)
    ]),
    'embed_settings': {
        'icon_url': entity.EntityDetailProperty('icon_url', False, entity_property_name='IconSpriteId', transform_function=sprites.get_download_sprite_link_by_property),
        'footer': entity.EntityDetailProperty('history_note', False, transform_function=__get_historic_data_note)
    }
}


async def init() -> None:
    global SHORT_NAME_FONT
    SHORT_NAME_FONT = ImageFont.truetype(os.path.join(sprites.PWD, 'fonts', 'PSSClone', 'PSSClone.ttf'), 10)
    league_data = await core.get_data_from_path(LEAGUE_BASE_PATH)
    league_infos = utils.convert.xmltree_to_dict3(league_data)
    for league_info in sorted(list(league_infos.values()), key=lambda league_info: int(league_info['MinTrophy'])):
        league_info['MinTrophy'] = int(league_info['MinTrophy'])
        league_info['MaxTrophy'] = int(league_info['MaxTrophy'])
        LEAGUE_INFOS_CACHE.append(league_info)