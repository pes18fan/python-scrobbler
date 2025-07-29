# python-scrobbler

A simple Python script that utilizes the `pylast` library and DBus to scrobble
tracks played on local music players to Last.fm.

>[!note]
>The scrobbler deliberately avoids scrobbling from Spotify, as it has its own
>setting to integrate it with Last.fm.

To use it, you need to add a Last.fm API key and secret, and a session key to
`~/.config/python-scrobbler/config.ini` then run the script. To automate it, you
can make it a systemd service.

You can get an API key and secret by creating an API account at `https://last.fm/api`.
To get a session key, run `session_key_getter.py`. It will open a web URL where
you can connect the scrobbler to your Last.fm account. After authorizing from
that browser page, the session key will be saved at a file `.session_key`, from
which you can grab it and place it in `config.ini`.

This script will also grab the first artist from the artist tag, split by `,`.
This may cause issues if the artist's name itself has a comma, in which case you
can add the name to the `ARTISTS_WITH_COMMAS` table.
