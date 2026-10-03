

; Define constants
#UDP_IP = "192.168.99.109"
#UDP_PORT = 6789
#SPEED = "20"

Global MSG_TX_1.s = "CQ CQ de SV0SYH SV0SYH K"
Global MSG_TX_2.s = "NAME ONDRA loc KN10LO K"
Global MSG_TX_3.s = ""
Global MSG_TX_4.s = "TU 73 de SV0SYH"
Global MSG_TX_5.s = "de SV0SYH SV0SYH"
Global RPT.s = "599"

; Define UDP Socket
Global udpSocket = OpenNetworkConnection(#UDP_IP, #UDP_PORT,#PB_Network_UDP)

If udpSocket = 0
  MessageRequester("Error", "Unable to open UDP connection.")
  End
EndIf

; Function to send message
Procedure SendMessage(message.s)
  If udpSocket
    SendNetworkString(udpSocket, message)
  EndIf
EndProcedure

; Function to simulate `upload_to_cloudlog` from Python script
Procedure UploadToCloudlog(baseUrl.s, apiKey.s, stationId.s, payload.s)
  Define jsondata.s
  jsondata = "{'key':'" + apiKey + "', 'station_profile_id':'" + stationId + "', 'type':'adif', 'string':'" + payload + "'}"
  
  ; Example HTTP POST request code would go here, depending on HTTP support libraries in PureBasic
  ; Using built-in PureBasic networking libraries to perform requests
EndProcedure

; Callback functions to handle button events
Procedure Msg1Callback()
  Debug "Sending - " + MSG_TX_1
  SendMessage(MSG_TX_1)
EndProcedure

Procedure Msg2Callback()
  Debug "Sending - " + MSG_TX_2
  SendMessage(MSG_TX_2)
EndProcedure

Procedure Msg3Callback()
  MSG_TX_3 = GetGadgetText(9)
  Debug "Sending - " + MSG_TX_3
  SendMessage(MSG_TX_3)
EndProcedure

Procedure Msg4Callback()
  Debug "Sending - " + MSG_TX_4
  SendMessage(MSG_TX_4)
EndProcedure

Procedure Msg5Callback()
  Debug "Sending - " + MSG_TX_5
  SendMessage(MSG_TX_5)
EndProcedure

Procedure LogQSOCallback()
  Debug "LOG QSO"
  Define dateStr.s, timeStr.s
  dateStr = FormatDate("%Y%m%d", Date())
  timeStr = FormatDate("%H%M%S", Date())
  
  ; Format ADIF template (example replacement)
  Define log.s
  log = "<BAND:4>13cm\n<BAND_RX:3>3cm\n<CALL:" + Str(Len(MSG_TX_1)) + ">" + MSG_TX_1 + "\n<GRIDSQUARE:6>KN10LO\n<MODE:2>CW\n<PROP_MODE:3>SAT\n<RST_RCVD:3>599\n<RST_SENT:3>599\n<SAT_MODE:3>S/X\n<SAT_NAME:6>QO-100\n<FREQ:8>2400.025\n<QSO_DATE:8>" + dateStr + "\n<TIME_ON:6>" + timeStr + "\n<EOR>"
  
  Debug log
  ; UploadToCloudlog("url", "api_key", "station_id", log)
EndProcedure

; GUI Creation
OpenWindow(0, 100, 100, 475, 220, "QO100TX - CW Daemon Client")
ButtonGadget(1, 10, 10, 100, 30, "CQ CQ")
BindGadgetEvent(1, @Msg1Callback())

StringGadget(2, 120, 10, 100, 20, "Call")
ButtonGadget(3, 230, 10, 50, 20, "CP")

TextGadget(4, 10, 50, 100, 20, "RPT:")
StringGadget(5, 120, 50, 50, 20, RPT)

ButtonGadget(6, 10, 90, 100, 30, "73 73")
BindGadgetEvent(6, @Msg4Callback())

TextGadget(7, 10, 130, 100, 20, "LOC:")
StringGadget(8, 120, 130, 50, 20, "")

ButtonGadget(9, 10, 170, 100, 30, "de ..")
BindGadgetEvent(9, @Msg5Callback())

ButtonGadget(10, 130, 170, 100, 30, "Log QSO")
BindGadgetEvent(10, @LogQSOCallback())

; Main event loop
Repeat
  Event = WaitWindowEvent()
  
  ; Check and handle window events if needed
Until Event = #PB_Event_CloseWindow

CloseNetworkConnection(udpSocket)
End

; IDE Options = PureBasic 6.12 LTS (Linux - x64)
; CursorPosition = 15
; Folding = --
; EnableXP
; DPIAware