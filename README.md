# vaultly-ytdlp

yt-dlp microservice for Vaultly. Deployed on Render.com free tier.

## Endpoints

- `GET /ping` — keep-alive
- `GET /info?url=<video_url>` — fetch video metadata
- `GET /download?url=<video_url>&format=mp4_480` — get direct download URL

## Format options
`mp4_480` `mp4_720` `mp4_1080` `mp4_4k` `mp3_128` `mp3_320`
