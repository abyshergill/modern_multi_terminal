TMPL_SSH_LOGIN = """; Tera Term SSH Auto-Login Template
connect '192.168.1.50 /ssh /2 /auth=password /user=admin /passwd=SecretPassword123'
wait '$'
sendln "echo 'Successfully logged in via TTL script!'"
sendln "uptime"
"""

TMPL_PY_AUTO = """# Python Terminal Automation Script
print("--- Starting Automated Server Check ---")
send("whoami")
wait(1.0)
send("pwd")
wait(1.0)
send("df -h")
wait(2.0)
print("--- Sequence Completed Successfully ---")
"""

TMPL_SERIAL_AT = """# Serial AT Command Hardware Tester
print("Initializing AT Modem Inquiry...")
send("AT")
wait(0.5)
send("AT+GMI")
wait(0.5)
send("AT+GMM")
wait(0.5)
print("Modem test finished.")
"""

TMPL_TTL_BATCH = """; Batch Command Sender with Delays
sendln "cd /var/log"
pause 2
sendln "ls -lh"
pause 1
sendln "tail -n 15 syslog"
"""