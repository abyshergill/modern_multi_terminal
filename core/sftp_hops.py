from __future__ import annotations
import paramiko

def get_hops(session):
    """Lazily initialize hop 0 (the direct connection) and return the hop list."""
    if not session.sftp_hops:
        if not (session.connection and session.connection.label == "SSH"):
            raise RuntimeError("Active connection is not SSH")
        sftp = session.connection.get_sftp()
        host = getattr(session.connection, "host", "Hop 1")
        session.sftp_hops.append({"label": f"Hop 1: {host}", "client": None, "sftp": sftp})
        session.active_hop_index = 0
    return session.sftp_hops

def add_jump_hop(session, host: str, port: int, username: str, password: str):
    """Tunnel a new SSH+SFTP connection through the currently active hop."""
    hops = get_hops(session)
    last = hops[session.active_hop_index]

    if last["client"] is not None:
        transport = last["client"].get_transport()
    else:
        transport = session.connection.client.get_transport()

    if transport is None or not transport.is_active():
        raise RuntimeError("Underlying hop transport is not active")

    channel = transport.open_channel("direct-tcpip", (host, port), ("127.0.0.1", 0))

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username or None,
        password=password or None,
        sock=channel,
        look_for_keys=not bool(password),
        allow_agent=not bool(password),
        timeout=15,
    )
    sftp = client.open_sftp()

    label = f"Hop {len(hops) + 1}: {username + '@' if username else ''}{host}"
    hops.append({"label": label, "client": client, "sftp": sftp})
    session.active_hop_index = len(hops) - 1
    return hops[-1]

def get_active_sftp(session):
    hops = get_hops(session)
    return hops[session.active_hop_index]["sftp"]

def remove_last_hop(session):
    """Close and drop the deepest hop, falling back to the previous one."""
    if len(session.sftp_hops) <= 1:
        return
    hop = session.sftp_hops.pop()
    try:
        if hop.get("sftp"):
            hop["sftp"].close()
    except Exception:
        pass
    try:
        if hop.get("client"):
            hop["client"].close()
    except Exception:
        pass
    session.active_hop_index = len(session.sftp_hops) - 1
