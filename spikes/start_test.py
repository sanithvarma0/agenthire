"""Start one phase 0 test against the running throwaway worker. Not product code.

    python spikes/start_test.py sarvam +91XXXXXXXXXX     # phone call, Sarvam speech
    python spikes/start_test.py realtime +91XXXXXXXXXX   # phone call, OpenAI speech-to-speech
    python spikes/start_test.py avatar av_XXXX           # browser test with an avatar; prints a link
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv
from livekit import api

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
AGENT_NAME = "agenthire-spike"


async def main() -> None:
    mode = sys.argv[1]
    argument = sys.argv[2] if len(sys.argv) > 2 else None
    language = sys.argv[3] if len(sys.argv) > 3 else ("en" if mode == "avatar" else "te")
    room = f"spike-{mode}-{secrets.token_hex(3)}"
    metadata: dict[str, str] = {"mode": mode, "language": language}
    if mode == "avatar":
        metadata["avatar_id"] = argument or ""
    elif argument:
        metadata["phone"] = argument

    lk = api.LiveKitAPI(os.environ["LIVEKIT_URL"], os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=120))
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=room, metadata=json.dumps(metadata)))
    finally:
        await lk.aclose()
    print("room:", room)

    if mode == "avatar":
        token = (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
                 .with_identity("tester").with_name("Tester")
                 .with_grants(api.VideoGrants(room_join=True, room=room)).to_jwt())
        query = urllib.parse.urlencode({"liveKitUrl": os.environ["LIVEKIT_URL"], "token": token})
        print("open this link in Chrome and allow the microphone:")
        print("https://meet.livekit.io/custom?" + query)


if __name__ == "__main__":
    asyncio.run(main())
