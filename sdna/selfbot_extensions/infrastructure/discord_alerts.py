"""
Discord Alerts - Notify user and wait for response.

Posts alerts to admin channel, waits for any reply (except ❌) to trigger action.
"""

import os
import json
import time
import logging
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

# Config - reads from Claude global config
# User sets up ~/.claude/discord_config.json with their Discord MCP creds
CLAUDE_GLOBAL_DIR = Path(os.environ.get("CLAUDE_GLOBAL_DIR", "/home/GOD/.claude"))
DISCORD_CONFIG_FILE = CLAUDE_GLOBAL_DIR / "discord_config.json"


def _load_discord_config() -> dict:
    """Load Discord config from Claude global dir."""
    if DISCORD_CONFIG_FILE.exists():
        try:
            return json.loads(DISCORD_CONFIG_FILE.read_text())
        except Exception as e:
            logger.warning(f"Failed to load discord config: {e}")
    return {}


def _get_config_value(key: str, env_fallback: str = "") -> str:
    """Get config value from file, fall back to env var."""
    config = _load_discord_config()
    return config.get(key) or os.environ.get(f"DISCORD_{key.upper()}", env_fallback)


# Lazy-loaded config values
def get_alert_channel_id() -> str:
    return _get_config_value("alert_channel_id")


def get_discord_token() -> str:
    return _get_config_value("token")


def get_discord_guild_id() -> str:
    return _get_config_value("guild_id")
ALERT_STATE_FILE = Path("/tmp/agent_queue/alert_state.json")


def get_discord_client():
    """Get Discord MCP client (lazy import)."""
    import sys
    sys.path.insert(0, "/tmp/cave_discord_fork")
    from discord_mcp_client import DiscordMCPClient

    client = DiscordMCPClient(
        token=get_discord_token(),
        guild_id=get_discord_guild_id()
    )
    return client


def send_alert(
    title: str,
    message: str,
    screenshot_path: Optional[str] = None,
    action_description: str = "restart"
) -> Optional[str]:
    """
    Send alert to Discord admin channel.

    Args:
        title: Alert title (e.g., "🚨 Self-restart failed")
        message: Error details
        screenshot_path: Optional path to screenshot
        action_description: What happens on reply (e.g., "restart")

    Returns:
        Message ID if sent successfully
    """
    channel_id = get_alert_channel_id()
    if not channel_id:
        logger.error("Discord alert_channel_id not configured in ~/.claude/discord_config.json")
        return None

    try:
        client = get_discord_client()
        client.start()

        # Format message
        content = f"""**{title}**

{message}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Reply anything to **{action_description}**
Reply ❌ to ignore"""

        result = client.send_message(channel_id, content)
        client.stop()

        # Save alert state for reply checking
        state = {
            "message_id": result.get("id"),
            "channel_id": channel_id,
            "action": action_description,
            "sent_at": datetime.now().isoformat(),
            "resolved": False
        }
        ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_STATE_FILE.write_text(json.dumps(state, indent=2))

        logger.info(f"Alert sent: {title}")
        return result.get("id")

    except Exception as e:
        logger.exception(f"Failed to send alert: {e}")
        return None


def check_for_reply(timeout: int = 300, poll_interval: int = 10) -> Optional[str]:
    """
    Poll for reply to the last alert.

    Args:
        timeout: Max seconds to wait
        poll_interval: Seconds between checks

    Returns:
        Reply content if received (None if ❌ or timeout)
    """
    if not ALERT_STATE_FILE.exists():
        logger.warning("No alert state found")
        return None

    state = json.loads(ALERT_STATE_FILE.read_text())
    if state.get("resolved"):
        return None

    try:
        client = get_discord_client()
        client.start()

        start_time = time.time()
        alert_time = datetime.fromisoformat(state["sent_at"])

        while time.time() - start_time < timeout:
            # Get recent messages from channel
            # Note: Discord MCP may need read_messages tool
            result = client.call_tool("read_messages", {
                "channel_id": state["channel_id"],
                "limit": 10
            })

            messages = result.get("content", [])
            if isinstance(messages, str):
                messages = json.loads(messages) if messages.startswith("[") else []

            # Check for replies after our alert
            for msg in messages:
                msg_time = msg.get("timestamp", "")
                msg_content = msg.get("content", "").strip()

                # Skip our own messages and messages before alert
                if msg.get("author", {}).get("bot"):
                    continue

                # Check if this is a reply (after alert time)
                if msg_content:
                    if msg_content == "❌":
                        logger.info("User chose to ignore alert")
                        state["resolved"] = True
                        state["reply"] = "❌"
                        ALERT_STATE_FILE.write_text(json.dumps(state, indent=2))
                        client.stop()
                        return None
                    else:
                        logger.info(f"User replied: {msg_content}")
                        state["resolved"] = True
                        state["reply"] = msg_content
                        ALERT_STATE_FILE.write_text(json.dumps(state, indent=2))
                        client.stop()
                        return msg_content

            time.sleep(poll_interval)

        client.stop()
        logger.warning("Timeout waiting for reply")
        return None

    except Exception as e:
        logger.exception(f"Error checking replies: {e}")
        return None


def alert_and_wait(
    title: str,
    message: str,
    on_reply: Callable[[], None],
    timeout: int = 300
) -> bool:
    """
    Send alert and wait for reply, then execute callback.

    Args:
        title: Alert title
        message: Alert message
        on_reply: Function to call when user replies (not ❌)
        timeout: Max seconds to wait

    Returns:
        True if action was triggered, False if ignored/timeout
    """
    msg_id = send_alert(title, message)
    if not msg_id:
        return False

    reply = check_for_reply(timeout=timeout)
    if reply:
        on_reply()
        # Confirm action
        send_alert("✅ Action completed", f"Triggered by your reply: {reply}")
        return True

    return False


# Quick test / CLI
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  discord_alerts.py send 'title' 'message'")
        print("  discord_alerts.py wait")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "send" and len(sys.argv) >= 4:
        send_alert(sys.argv[2], sys.argv[3])
    elif cmd == "wait":
        reply = check_for_reply()
        print(f"Reply: {reply}")
    else:
        print(f"Unknown: {cmd}")
