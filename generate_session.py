import asyncio
from telethon.sessions import StringSession
from telethon import TelegramClient
import os

API_ID = 30275439 # Replace with your API ID
API_HASH = '1c616ba10f54126963bb307125e64bd3' # Replace with your API Hash

async def main():
    # The first parameter is the session file name. We use StringSession() to generate a string session.
    # If you are signing in as a bot, you would use client.start(bot_token=BOT_TOKEN)
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start()

    print("Successfully signed in. Here is your session string:")
    session_string = client.session.save()
    print(f"\n{session_string}\n")
    print("Keep this string safe! Anyone with it can access your account.")
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())

