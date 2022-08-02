# Spotify for twitter banner - Adapted for Github READMEs

from __future__ import annotations

import base64
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Literal, cast

import requests
from github import Github, InputGitAuthor
from PIL import Image, ImageDraw, ImageFont

PYTHON_VERSION = (
    f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
)

STATUS_MAPPING = {
    True: ["Vibing to", "Binging to", "Listening to", "Obsessed with"],
    False: ["Was listening to", "Previously binging to", "Was vibing to"],
}


class Fonts:
    # Base font path
    FONT_PATH = "fonts/"

    FIRA_REGULAR = FONT_PATH + "FiraCode-Regular.ttf"
    FIRA_MEDIUM = FONT_PATH + "FiraCode-Medium.ttf"
    FIRA_SEMIBOLD = FONT_PATH + "FiraCode-SemiBold.ttf"

    POPPINS_REGULAR = FONT_PATH + "Poppins-Regular.ttf"
    POPPINS_SEMIBOLD = FONT_PATH + "Poppins-SemiBold.ttf"

    ARIAL = FONT_PATH + "arial-unicode-ms.ttf"


# Region: Models
@dataclass
class Song:
    name: str
    artist: str
    album: str

    is_explicit: bool

    currently_playing_type: Literal["track", "episode"]
    is_now_playing: bool

    image_url: str
    image: Image.Image = field(init=False, repr=False)

    progress_ms: int | None
    duration_ms: int | None

    def __post_init__(self):
        self.image = Image.open(BytesIO(requests.get(self.image_url).content))

    @classmethod
    def from_json(cls, song: dict[str, Any]) -> "Song":
        is_now_playing = song["is_now_playing"]
        currently_playing_type = song["currently_playing_type"]

        progress_ms = song.get("progress_ms")
        duration_ms = song.get("duration_ms")

        if currently_playing_type == "track":
            artist_name = song["artists"][0]["name"].replace("&", "&amp;")
            song_name = song["name"].replace("&", "&amp;")
            album_name = song["album"]["name"].replace("&", "&amp;")

            img_url = song["album"]["images"][1]["url"]
        else:
            artist_name = song["show"]["publisher"].replace("&", "&amp;")
            song_name = song["name"].replace("&", "&amp;")
            album_name = song["show"]["name"].replace("&", "&amp;")

            img_url = song["images"][1]["url"]

        return cls(
            song_name,
            f"By {artist_name}",
            f"On {album_name}",
            song["explicit"],
            currently_playing_type,
            is_now_playing,
            img_url,
            progress_ms,
            duration_ms,
        )


# Endregion

# Region: Spotify API wrapper
class Spotify:
    RETRY_ATTEMPTS = 3
    USER_AGENT = f"Rohith04MVK Readme status - Python/{PYTHON_VERSION} Requests/{requests.__version__}"
    BASE_URL = "https://api.spotify.com/v1"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret

        self.bearer_info = None
        self.refresh_token = refresh_token

    def get_bearer_info(self) -> dict[str, Any]:
        """Get the bearer info containing the access token to access the spotify endpoints."""
        if not self.refresh_token:
            raise Exception("No refresh token provided.")

        token = self.generate_base64_token()

        headers = {"Authorization": f"Basic {token}"}
        data = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}

        # Get the bearer info.
        response = requests.post(
            "https://accounts.spotify.com/api/token", headers=headers, data=data
        )

        # Check if the request was successful.
        if response.status_code != 200:
            raise Exception("Failed to get bearer info.")

        # Return the bearer info.
        info = response.json()

        if "error" in info:
            raise Exception(f"Failed to get bearer info: {info['error']}")

        return info

    def fetch(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, Any] | None = None,
        data: Any | None = None,
    ) -> dict[str, Any] | None:
        if not headers:
            headers = {}

        # Check if Authorization exists.
        if "Authorization" not in headers:
            # Check if bearer info exists.
            if self.bearer_info is None:
                self.bearer_info = self.get_bearer_info()

            # Set the Authorization header.
            headers["Authorization"] = f"Bearer {self.bearer_info['access_token']}"

        headers = {
            "User-Agent": self.USER_AGENT,
            "Content-Type": "application/json",
            **headers,
        }

        # Perform request with retries.
        for _ in range(self.RETRY_ATTEMPTS):
            response = requests.request(
                method, self.BASE_URL + path, headers=headers, json=data
            )

            if response.status_code == 200:
                return response.json()

            try:
                data = json.loads(response.text)
            except json.decoder.JSONDecodeError:
                data = None

            if 200 <= response.status_code < 300:
                return data

            # Handle ratelimited requests
            if response.status_code == 429:
                retry_after = int(response.headers["Retry-After"])

                time.sleep(retry_after)
                continue

            # Handle access token expired
            if response.status_code == 401:
                self.bearer_info = self.get_bearer_info()

                continue

            # Ignore anything 5xx
            if response.status_code >= 500:
                continue

            # Route not found error - This won't happen most of the times
            if response.status_code == 404:
                return None

            # If it's an internal route for the app
            if response.status_code == 403:
                return None

    # Utility methods
    def generate_base64_token(self) -> str:
        return base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode("utf-8")

    @staticmethod
    def _form_url(url: str, data: dict[str, Any]) -> str:
        url += "?" + "&".join(
            [f"{dict_key}={dict_value}" for dict_key, dict_value in data.items()]
        )

        return url

    # Main endpoints
    def currently_playing(self) -> dict[str, Any] | None:
        """Get the currently playing song/podcast."""
        return self.fetch(
            "GET",
            self._form_url(
                "/me/player/currently-playing", {"additional_types": "track,episode"}
            ),
        )

    def is_playing(self) -> bool:
        """Check if the user is currently listening to music."""
        currently_playing = self.currently_playing()

        if currently_playing:
            return currently_playing["is_playing"]

        return False

    def recently_played(
        self, limit: int = 20, before: str | None = None, after: str | None = None
    ) -> dict[str, Any]:
        """Get recently played tracks."""
        data: dict[str, Any] = {"limit": limit}

        if before:
            data["before"] = before

        if after:
            data["after"] = after

        return cast(
            dict[str, Any],
            self.fetch("GET", self._form_url("/me/player/recently-played", data)),
        )

    def top_tracks(
        self,
        limit: int = 20,
        offset: int = 0,
        time_range: Literal["short_term", "medium_term", "long_term"] | None = None,
    ) -> dict[str, Any]:
        """Get top tracks of the user."""
        data: dict[str, Any] = {"limit": limit, "offset": offset}

        if time_range:
            data["time_range"] = time_range

        return cast(
            dict[str, Any], self.fetch("GET", self._form_url("/me/top/tracks", data))
        )


# Endregion

# Region: Image generation
def truncate_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if font.getsize(text)[0] <= max_width:
        return text.strip()

    while font.getsize(text)[0] > max_width:
        text = text[:-1]

    return text.strip() + ".."


def midpoint(start: int, end: int, text: str, font: ImageFont.FreeTypeFont) -> float:
    """Calculate the midpoint between two points with the text width of the font."""
    mid = (start + end) / 2

    text_width = font.getsize(text)[0]

    return mid - (text_width / 2)


def draw_tag(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    color: tuple,
) -> None:
    """Draw a tag with black text and specified color as background."""
    draw.rectangle(
        (x, y, x + font.getsize(text)[0] + 10, y + font.getsize(text)[1] + 10),
        fill=color,
    )
    draw.text((x + 5, y + 5), text, font=font, fill=(0, 0, 0))


def generate_image(
    status: str,
    song: Song,
    top_tracks: list,
    image_save_path: str,
    show_only: bool = False,
) -> None:
    # Get the top tracks filtered by grabbing the name, and artist.
    top_tracks = [
        {
            "name": track["name"].replace("&", "&amp;"),
            "artist": track["artists"][0]["name"].replace("&", "&amp;"),
        }
        for track in top_tracks
    ]

    # Create an image.
    img = Image.new("RGB", (1500, 500), (18, 18, 18))
    draw = ImageDraw.Draw(img)

    # Load fonts
    fira_code = ImageFont.truetype(Fonts.FIRA_REGULAR, size=23)
    fira_code_small = ImageFont.truetype(Fonts.FIRA_REGULAR, size=18)
    poppins = ImageFont.truetype(Fonts.POPPINS_REGULAR, size=27)
    poppins_semibold = ImageFont.truetype(Fonts.POPPINS_SEMIBOLD, size=27)

    # Add the song image to the image.
    song.image.thumbnail((350, 350), Image.ANTIALIAS)
    img.paste(song.image, (50, 100))

    # Add the status text above the image, aligned in the center, using midpoint from coordinates of 50 to 400.
    draw.text(
        (50, 50), status, (255, 255, 255), font=poppins,
    )

    # Add the song name, artist name, and album name in the right side of the image.
    white = "#ffffff"

    draw.text(
        (400, 150),
        truncate_text(song.name, poppins, 600),
        fill=white,
        font=poppins_semibold,
    )

    draw.text(
        (400, 200), truncate_text(song.artist, poppins, 600), fill=white, font=poppins,
    )

    draw.text(
        (400, 250), truncate_text(song.album, poppins, 600), fill=white, font=poppins,
    )

    # Add explicit tag.
    if song.is_explicit:
        draw_tag(draw, 400, 300, "EXPLICIT", fira_code_small, (255, 255, 255))

    # Add a white line in left of top tracks, to separate it.
    draw.line((img.size[0] - 375, 100, img.size[0] - 375, 400,), fill=white)

    # Assign top songs name and artists font.
    top_tracks = [
        {
            "name": truncate_text(track["name"], poppins, 300),
            "artist": truncate_text(track["artist"], fira_code, 300),
        }
        for track in top_tracks
    ]

    # Add title containing top tracks on top before displaying the top tracks.
    draw.text(
        (img.size[0] - 350, 50), "Top Tracks:", fill=white, font=poppins_semibold,
    )

    # Add the top songs to the right side of the image.
    for i, track in enumerate(top_tracks):
        # Add the song name.
        draw.text(
            (img.size[0] - 350, 100 + (i * 50) + (i * 10),),
            track["name"],
            font=poppins,
            fill=(255, 255, 255),
        )

        # Add the artist name.
        draw.text(
            (img.size[0] - 350, 100 + (i * 50) + (i * 10) + 35,),
            track["artist"],
            font=fira_code_small,
            fill=(255, 255, 255),
        )

    # Add song progress bar, if listening currently.
    if song.is_now_playing:
        total_time = cast(int, song.duration_ms)
        current_time = cast(int, song.progress_ms)

        # Calculate the progress bar width.
        progress_bar_width = (current_time / total_time) * 700

        # Draw the progress bar. White for the covered progress, Gray for the left progress.
        # Draw from right of the image till the top tracks.
        draw.rectangle(((375, 425), (1100, 430)), fill="#B3B3B3")
        draw.rectangle(((375 + progress_bar_width, 425), (1100, 430)), fill="#404040")

        # Add the time progress text, in the center of the progress bar. Display current time and total time.
        current_progress = f"{current_time // 60000}:{current_time // 1000 % 60:02d}"
        total_progress = f"{total_time // 60000}:{total_time // 1000 % 60:02d}"

        # Display current progress in the progress bar start.
        draw.text(
            (375, 440,), current_progress, font=poppins, fill=(255, 255, 255),
        )

        # Display total progress in the progress bar end.
        draw.text(
            (1100 - (len(total_progress) * 10), 440,),
            total_progress,
            font=poppins,
            fill=(255, 255, 255),
        )

    # Show the image, if show only is enabled.
    if show_only:
        img.show()
    else:
        # Save the image to the path specified.
        img.save(image_save_path, format="JPEG", quality=100)


# Endregion

# Region: Utilities
def get_song_info(spotify: Spotify) -> Song:
    # Get the currently playing track.
    now_playing = spotify.currently_playing()

    # Check if song is playing.
    if now_playing and now_playing != {}:
        song = now_playing["item"]

        # Ensure that there is a currently playing type
        song["currently_playing_type"] = now_playing["currently_playing_type"]

        # Ensure now playing exists
        song["is_now_playing"] = now_playing["is_playing"]

        # `progress_ms` is not in `song`, and instead in `now_playing`
        song["progress_ms"] = now_playing["progress_ms"]
    else:
        # Get recently played songs.
        recently_played = spotify.recently_played()

        # Get a random song.
        size_recently_played = len(recently_played["items"])
        idx = random.randint(0, size_recently_played - 1)

        song = recently_played["items"][idx]["track"]

        # Add track type, if not actively playing.
        song["currently_playing_type"] = "track"
        song["is_now_playing"] = False

    return Song.from_json(song)


# Endregion

spotify = Spotify(
    os.environ["SPOTIFY_CLIENT_ID"],
    os.environ["SPOTIFY_CLIENT_SECRET"],
    os.environ["SPOTIFY_REFRESH_TOKEN"],
)

top_tracks = spotify.top_tracks(limit=5)
top_tracks = [track for track in top_tracks["items"]]

song = get_song_info(spotify=spotify)
status = random.choice(STATUS_MAPPING[song.is_now_playing]) + ":"

generate_image(status, song, top_tracks, "spotify-banner.jpeg")

# Push to github
github = Github(os.environ["GITHUB_TOKEN"])

repo = github.get_repo("Rohith04MVK/Rohith04MVK")
committer = InputGitAuthor('readme-bot', '41898282+github-actions[bot]@users.noreply.github.com')

with open("spotify-banner.jpeg", "rb") as f:
    data = f.read()

try:
    contents = repo.get_contents("spotify/spotify-banner.jpeg")
    repo.update_file(contents.path, "Charts Updated", data, contents.sha, committer=committer)
except Exception as e:
    repo.create_file("spotify/spotify-banner.jpeg", "Charts Added", data, committer=committer)
