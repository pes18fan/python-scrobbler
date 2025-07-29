#!/usr/bin/env python3
import os
import sys
import logging
import configparser
import time

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import pylast

ARTISTS_WITH_COMMAS = ["Tyler, the Creator", "Dream, Ivory"]

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# Load the config
CONFIG_PATH = os.path.expanduser("~/.config/scrobbler/config.ini")
if not os.path.isfile(CONFIG_PATH):
    log.error("Config file not found: %s", CONFIG_PATH)
    sys.exit(1)

config = configparser.ConfigParser()
config.read(CONFIG_PATH)

try:
    api_key = config["lastfm"]["api_key"]
    api_secret = config["lastfm"]["api_secret"]
    session_key = config["lastfm"]["session_key"]
    log.info("Loaded config from %s", CONFIG_PATH)
except KeyError as e:
    log.exception("Missing config entry: %s", e)
    sys.exit(1)

# Initialize Last.fm network
try:
    network = pylast.LastFMNetwork(
        api_key=api_key, api_secret=api_secret, session_key=session_key
    )
    log.info("Connected to Last.fm as session %s", session_key[:8] + "...")
except Exception:
    log.exception("Failed to initialize pylast network")
    sys.exit(1)

# Set up D-Bus
DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()

players = {}

# memoize the sender->player relations to avoid overly high memory usage
sender_to_players = {}

current_player = "placeholder"
pause_timer = None


def get_player_name(sender):
    # See if the player name is memoized
    try:
        return sender_to_players[sender]
    except KeyError:
        pass

    dbus_obj = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
    iface = dbus.Interface(dbus_obj, "org.freedesktop.DBus")
    names = iface.ListNames()

    player_name = next(
        (
            name
            for name in names
            if name.startswith("org.mpris.MediaPlayer2.")
            and bus.name_has_owner(name)
            and bus.get_name_owner(name) == sender
        ),
    )
    sender_to_players[sender] = player_name
    return player_name


def properties_changed(interface, changed, invalidated, sender):
    """Handle new metadata or playback status changes."""
    global current_player
    try:
        if interface != "org.mpris.MediaPlayer2.Player":
            return

        player = get_player_name(sender)
        if "spotify" in player:
            return

        info = players.setdefault(
            sender,
            {
                "proxy": bus.get_object(sender, "/org/mpris/MediaPlayer2"),
                "scrobbled": False,
                "status": "Stopped",
                "last_position": 0,
                "listened": 0,
            },
        )
        player_name = player.split(".")[-1]

        if "metadata" not in info and player_name != current_player:
            log.info("Detected player: %s", player_name)
            current_player = player_name

        if "Metadata" in changed:
            md = changed["Metadata"]
            info.update(
                {
                    "metadata": md,
                    "start_time": int(time.time()),
                    "scrobbled": False,
                    "last_position": 0,
                    "listened": 0,
                }
            )

        if "PlaybackStatus" in changed:
            new_status = changed["PlaybackStatus"]
            info["status"] = new_status
            log.info("Player %s status -> %s", player_name, new_status)

            if new_status == "Playing":
                md = info.get("metadata")
                if md:
                    artist = (md.get("xesam:artist") or [""])[0]

                    if artist not in ARTISTS_WITH_COMMAS:
                        artist = artist.split(",")[0]

                    title = md.get("xesam:title", "")
                    album = md.get("xesam:album", "")

                    try:
                        log.info("Now playing %s - %s [%s]", artist, title, album)
                        network.update_now_playing(artist, title, album)
                    except Exception:
                        log.exception(
                            "Failed update_now_playing for %s - %s from %s [%s]",
                            artist,
                            title,
                            album,
                        )
            else:
                log.info("Waiting for paused/stopped track to start playing...")
    except Exception:
        log.exception("Error in properties_changed handler")


# Register signal receiver for PropertiesChanged
bus.add_signal_receiver(
    properties_changed,
    dbus_interface="org.freedesktop.DBus.Properties",
    signal_name="PropertiesChanged",
    path="/org/mpris/MediaPlayer2",
    sender_keyword="sender",
)


def check_positions():
    """Every 5 seconds, scrobble any track played 2/3 through."""
    for sender, info in list(players.items()):
        if info.get("status") != "Playing":
            continue

        meta = info.get("metadata", {})
        length = meta.get("mpris:length", 0)
        if not length:
            continue

        try:
            pos = info["proxy"].Get(
                "org.mpris.MediaPlayer2.Player",
                "Position",
                dbus_interface="org.freedesktop.DBus.Properties",
            )
        except dbus.exceptions.DBusException:
            log.warning("Lost connection to %s, removing", sender)
            players.pop(sender, None)
            continue

        artist = meta.get("xesam:artist", [""])[0]
        if not hasattr(ARTISTS_WITH_COMMAS, artist):
            artist = artist.split(",")[0]

        title = meta.get("xesam:title", "")
        album = meta.get("xesam:album", "")

        # keep the now playing status updated
        status = info.get("status", "")
        if status == "Playing":
            network.update_now_playing(artist, title, album)

        # calculate the duration that has been listened to
        delta = pos - info["last_position"]
        if delta > 0:
            info["listened"] += delta
        info["last_position"] = pos

        if info["listened"] >= (2 * length) // 3 and not info["scrobbled"]:
            ts = info["start_time"]
            log.info(
                "Scrobbling after %.1f%% play: %s - %s [%s]",
                pos / length * 100,
                artist,
                title,
                album,
            )
            try:
                network.scrobble(artist, title, ts, album)
                info["scrobbled"] = True
            except Exception:
                log.exception("Failed scrobble for %s - %s [%s]", artist, title)

    return True  # Keep timeout alive


# Schedule position checks every 5 seconds
GLib.timeout_add_seconds(5, check_positions)

if __name__ == "__main__":
    try:
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        log.info("Shutting down.")
