print("--- Launching DevOps Python Pipeline ---")

# Connect programmatically using your arguments
"""
Replace xx.xxx.xx.xx  With actual Your IP
then change username with remote server username and password
By Default ssh port is 22.
"""
connect_ssh("xx.xxx.xx.xx", username="username", password="password", port=22)
wait(1.5)

# Send commands down the newly established wire
send("uname -a")
wait(1.0)
send("df -h")