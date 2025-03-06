import os
import asyncio
import discord
import aiohttp
from PIL import Image
from io import BytesIO
from datetime import datetime, timezone, timedelta
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport

TOKEN = "BOT_TOKEN"
CHANNEL_ID = 1334820874062135368

os.makedirs('images', exist_ok=True)

query = gql("""
query GetCampaigns($page: Int, $pageSize: Int) {
  campaigns(page: $page, pageSize: $pageSize) {
    identifier
    name
    description
    picture
    starting
    ending
    creator {
      address
    }
  }
}
""")

sent_campaigns = set()

async def fetch_campaigns(client, page, pageSize):
    variables = {"page": page, "pageSize": pageSize}
    try:
        result = await client.execute(query, variable_values=variables)
        return result.get('campaigns', [])
    except Exception as e:
        print(f"Error fetching campaigns page {page}: {e}")
        return []

async def download_and_save_image(image_url, identifier):
    print(f"Attempting to download image from {image_url} for campaign {identifier}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as response:
                if response.status != 200:
                    print(f"Failed to fetch image: HTTP {response.status}")
                    return None
                data = await response.read()
                image = Image.open(BytesIO(data))
                if image.mode == 'RGBA':
                    image = image.convert('RGB')
                image_path = os.path.join('images', f'{identifier}.webp')
                image.save(image_path, 'WEBP', quality=85)
                print(f"Successfully saved image to {image_path}")
                return image_path
    except Exception as e:
        print(f"Failed to download image for {identifier}: {e}")
        return None

def format_timestamp(timestamp):
    try:
        print(f"Formatting timestamp: {timestamp}")
        if timestamp is None or timestamp == 0:
            return "No date", None

        if isinstance(timestamp, (int, float)) and timestamp > 1e12:
            timestamp /= 1000
        elif timestamp < 1e9:
            return "Invalid timestamp", None

        dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        formatted = dt.strftime("%d/%m/%Y")
        print(f"Converted timestamp {timestamp} to {formatted}")
        return formatted, dt
    except Exception as e:
        print(f"Error formatting timestamp {timestamp}: {e}")
        return "Invalid date", None

async def process_campaigns(bot):
    transport = AIOHTTPTransport(url="https://graph.9lives.so/graphql")
    try:
        print("Initializing GraphQL client...")
        async with Client(transport=transport, fetch_schema_from_transport=True) as client:
            all_campaigns = []
            page = 1
            pageSize = 100

            print(f"Starting to fetch campaigns, max pages: 100")
            while page <= 100:
                print(f"Fetching page {page}...")
                campaigns = await fetch_campaigns(client, page, pageSize)
                if not campaigns:
                    print(f"No more campaigns on page {page}, stopping.")
                    break
                all_campaigns.extend(campaigns)
                page += 1

            print(f"Total Campaigns Fetched: {len(all_campaigns)}")

            print("Sample campaign data:")
            for i, campaign in enumerate(all_campaigns[:10]):
                print(
                    f"Campaign {i + 1}: Identifier={campaign.get('identifier', 'N/A')}, Starting={campaign.get('starting', 'N/A')}")

            current_date = datetime.now(timezone.utc)
            cutoff_date = datetime(2025, 2, 16, tzinfo=timezone.utc)
            print(f"Cutoff date set to: {cutoff_date.strftime('%d/%m/%Y')}")
            print(f"Current date set to: {current_date.strftime('%d/%m/%Y')}")

            valid_campaigns = {}

            print("Filtering campaigns...")
            for campaign in all_campaigns:
                identifier = campaign.get('identifier', 'N/A')
                if identifier in sent_campaigns:
                    print(f"Skipping already sent campaign: {identifier}")
                    continue

                start_raw = campaign.get('starting', 0)
                start_str, start_dt = format_timestamp(start_raw)

                cutoff_str = cutoff_date.strftime("%d/%m/%Y")
                current_str = current_date.strftime("%d/%m/%Y")
                cutoff_check = start_dt >= cutoff_date if start_dt else False
                current_check = start_dt <= current_date if start_dt else False

                print(
                    f"Campaign {identifier}: Raw Start={start_raw}, Formatted Start={start_str}, Cutoff Date={cutoff_str}, Current Date={current_str}, Cutoff Check={cutoff_check}, Current Check={current_check}")

                if start_dt and start_dt >= cutoff_date and start_dt <= current_date:  # Include campaigns from 16/02/2025 to now
                    valid_campaigns[identifier] = {
                        "identifier": identifier,
                        "name": campaign.get('name', 'N/A'),
                        "description": campaign.get('description', 'N/A'),
                        "picture_url": campaign.get('picture', ''),
                        "starting": start_str,
                        "starting_dt": start_dt,
                        "ending": format_timestamp(campaign.get('ending', 0))[0],
                        "creator_address": campaign.get('creator', {}).get('address', 'N/A')
                    }
                else:
                    print(f"Campaign {identifier} excluded: Not within date range (16/02/2025 to {current_str})")

            print(f"Found {len(valid_campaigns)} valid campaigns after filtering.")
            sorted_campaigns = sorted(valid_campaigns.values(), key=lambda x: x["starting_dt"])
            print(f"Sending {len(sorted_campaigns)} sorted campaigns to Discord...")
            await send_campaigns_to_discord(bot, sorted_campaigns)
    except Exception as e:
        print(f"Error in process_campaigns: {e}")

class CampaignButton(discord.ui.View):
    def __init__(self, campaign_url):
        super().__init__()
        self.add_item(discord.ui.Button(label="Go to Campaign", url=campaign_url, style=discord.ButtonStyle.link))

async def send_campaigns_to_discord(bot, campaigns):
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"Error: Cannot find Discord channel ID {CHANNEL_ID}.")
        return

    global sent_campaigns

    for campaign in campaigns:
        identifier = campaign["identifier"]
        if identifier in sent_campaigns:
            print(f"Skipping already sent campaign: {identifier}")
            continue

        campaign_link = f"https://9lives.so/campaign/{identifier}"
        print(f"Processing campaign {identifier} with image URL: {campaign['picture_url']}")
        image_path = await download_and_save_image(campaign["picture_url"], identifier) if campaign[
            "picture_url"] else None

        embed = discord.Embed(
            title=campaign["name"],
            description=campaign["description"][:2000],
            color=0x00ff00,
            url=campaign_link
        )
        embed.add_field(name="🕒 Start", value=campaign["starting"])
        embed.add_field(name="⏃ End", value=campaign["ending"])
        embed.add_field(name="👤 Creator", value=f"`{campaign['creator_address']}`", inline=False)

        try:
            if image_path:
                print(f"Sending embed with image for {identifier}")
                file = discord.File(image_path, filename="thumbnail.webp")
                embed.set_thumbnail(url="attachment://thumbnail.webp")
                await channel.send(file=file, embed=embed, view=CampaignButton(campaign_link))
            else:
                print(f"Sending embed without image for {identifier}")
                await channel.send(embed=embed, view=CampaignButton(campaign_link))

            sent_campaigns.add(identifier)
            print(f"Posted new campaign: {campaign['name']}")
        except Exception as e:
            print(f"Failed to send campaign {identifier}: {e}")

class DiscordBot(discord.Client):
    async def on_ready(self):
        print(f"Logged in as {self.user}")
        while True:
            try:
                await process_campaigns(self)
            except Exception as e:
                print(f"Critical error in main loop: {e}")
            await asyncio.sleep(90)  # 90 seconds restart time

intents = discord.Intents.default()
bot = DiscordBot(intents=intents)
bot.run(TOKEN)