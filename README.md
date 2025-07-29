# python-scrobbler

A simple Python script that utilizes the `pylast` library and DBus to scrobble
tracks played on local music players to Last.fm.

>[!note]
>The scrobbler deliberately avoids scrobbling from Spotify, as it has its own
>setting to integrate it with Last.fm.

To use it, you need to add a Last.fm API key and secret, and a session key to
`~/.config/python-scrobbler/config.ini` then run the script. To automate it, you
can make it a systemd service.
