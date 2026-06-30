# =======================================================
# Telnet Automated Login Script (.py)
# =======================================================

print("--- Launching Automated Telnet Sequence ---")

# Syntax: connect_telnet("Target_IP", port=Port_Number)
connect_telnet("192.168.1.50", port=23)

wait(1.0) # Give remote Telnet daemon a second to present banner
send("admin")

wait(1.0)
send("secretpass123")

wait(1.5)
send("show system uptime")

print("--- Sequence Complete ---")