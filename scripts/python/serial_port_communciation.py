print("--- Initializing Hardware Serial Diagnostic Sequence ---")

"""
Baudrate Depends upon the board. So Change accordingly to your board.
COM3 or other port. I recommend you check by connecting and disconnection to verify.

"""
# Connect programmatically to a COM port (Windows) or device path (Linux/macOS)
connect_serial("COM3", baudrate=115200)
wait(1.5)

# Query an attached microcontroller, modem, or switch console
send("AT")
wait(0.5)

send("ATI")
wait(1.0)

print("--- Hardware Inquiry Completed ---")