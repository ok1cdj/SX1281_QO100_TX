#
# Simple python program which emulates basic cwdaemon functions
#	- set wpm
#	- send message
#
# Use it to test the developed firmware of ESP32 or to test/debug your connectivity to ESP32 WiFi
#
# 2021, OM2JU, Jan Uhrin
#
#
#
import socket
from time import sleep

UDP_IP = "192.168.1.17"
UDP_PORT = 6789

MSG_TX_1 = "UDP Test"
MSG_SPEED_15 = chr(27) + '2' + "15" 
MSG_SPEED_30 = chr(27) + '2' + "30"


print("UDP target IP:", UDP_IP)
print("UDP target port:", UDP_PORT)
print("message:", MSG_TX_1)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP


print("Sending with 15wpm...")
sock.sendto(bytes(MSG_SPEED_15, "ascii"), (UDP_IP, UDP_PORT))
sleep(0.1)
sock.sendto(bytes(MSG_TX_1, "ascii"), (UDP_IP, UDP_PORT))

sleep(5)   # This delay shold allow to transmit complete message with 15wpm

print("Sending with 30wpm...")
sock.sendto(bytes(MSG_SPEED_30, "ascii"), (UDP_IP, UDP_PORT))
sleep(0.3)
sock.sendto(bytes(MSG_TX_1, "ascii"), (UDP_IP, UDP_PORT))

