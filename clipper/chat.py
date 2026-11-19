"""Read-only Twitch chat over IRC. Anonymous login, so no Twitch account is needed."""
from __future__ import annotations

import logging
import random
import socket
import ssl
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)
HOST, PORT = "irc.chat.twitch.tv", 6697


def twitch_chat(channel: str, on_message: Callable[[str], None], stop: threading.Event) -> None:
    channel = channel.lower().lstrip("#")
    while not stop.is_set():
        try:
            raw = socket.create_connection((HOST, PORT), timeout=30)
            sock = ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
            sock.settimeout(360)  # Twitch PINGs about every 5 min
            nick = f"justinfan{random.randint(10000, 99999)}"
            sock.sendall(f"PASS SCHMOOPIIE\r\nNICK {nick}\r\nJOIN #{channel}\r\n".encode())
            log.info("[%s] connected to chat", channel)
            buf = ""
            while not stop.is_set():
                data = sock.recv(8192)
                if not data:
                    break
                buf += data.decode("utf-8", "replace")
                while "\r\n" in buf:
                    line, buf = buf.split("\r\n", 1)
                    if line.startswith("PING"):
                        sock.sendall(f"PONG{line[4:]}\r\n".encode())
                    elif " PRIVMSG " in line:
                        parts = line.split(" PRIVMSG ", 1)[1].split(" :", 1)
                        if len(parts) == 2:
                            on_message(parts[1])
            sock.close()
        except OSError as e:
            log.warning("[%s] chat connection dropped (%s), reconnecting", channel, e)
        time.sleep(5)
