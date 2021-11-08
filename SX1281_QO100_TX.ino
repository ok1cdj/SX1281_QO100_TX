//
// 2021-08  QO-100 SAT CW Transmitter with OLED Display
// by Jan Uhrin, OM2JU and Ondrej Kolonicny, OK1CDJ
//
//
// States of program with explanation:
//
//  RUN     - main state, displays freq. and status, responds to keyer or received UDP packets
//  SET_PWM
//  SET_KEYER
//  SET_OFFSET
//  SET_SSID
//  SET_PWD
//  WIFI_RECONNECT
// ...
//
//
// Power level settings - from documentation of LoRa128xF27 module
// LEV dBm  mA    Reg value
// 9  26.4  520   13
// 8  25.5  426   10
// 7  23.4  343   7
// 6  20.85 268   4
// 5  18.26 229   1
// 4  15.2  182   -2
// 3  12.3  155   -5
// 2  9.3   138   -8
// 1  6.0   130   -12
// 0  3.0   125   -15
//
// SX128x datasheet p. 73:   Reg vale 0 = -18dBm, Reg value 31 = 13dBm  ==> PA of the module has gain 32.2 dB
//
//

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Preferences.h>

#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <AsyncUDP.h>
#include <SPIFFS.h>


#include "time.h"
#include <SPI.h>                                               //the lora device is SPI based so load the SPI library                                         
#include <SX128XLT.h>                                          //include the appropriate library  
#include "Settings.h"                                          //include the setiings file, frequencies, LoRa settings etc   


#define UDP_PORT 6789 // UDP port for CW 

#define SCREEN_WIDTH 128 // OLED display width, in pixels
#define SCREEN_HEIGHT 64 // OLED display height, in pixels

// Declaration for an SSD1306 display connected to I2C (SDA, SCL pins)
#define OLED_RESET     -1 // Reset pin # (or -1 if sharing Arduino reset pin)
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

#define PUSH_BTN_PRESSED 0
#define WAIT_Push_Btn_Release(milisec)  delay(milisec);while(digitalRead(ROTARY_ENC_PUSH)==0){}

// Webserver
AsyncWebServer server(80);
AsyncUDP udp;
QueueHandle_t queue;

String ssid       = "";
String password   = "";
String apikey     = "";
String sIP        = "";
String sGateway   = "";
String sSubnet    = "";
String sPrimaryDNS = "";
String sSecondaryDNS = "";
String wifiNetworkList = "";
String spwr = "";

String message;
String sspeed = "20";
String sfreq;
String scmd;
uint32_t speed = 20;

// web server requests
const char* PARAM_MESSAGE = "message";
const char* PARAM_FRQ_INDEX = "frq_index";
const char* PARAM_SPEED = "speed";
const char* PARAM_PWR = "pwr";
const char* PARAM_SSID = "ssid";
const char* PARAM_PASSWORD = "password";
const char* PARAM_APIKEY = "apikey";
const char* PARAM_DHCP = "dhcp";
const char* PARAM_CON = "con";
const char* PARAM_SUBNET = "subnet";
const char* PARAM_GATEWAY = "gateway";
const char* PARAM_PDNS = "pdns";
const char* PARAM_SDNS = "sdns";
const char* PARAM_LOCALIP = "localip";
const char* PARAM_CMD_B = "cmd_B";
const char* PARAM_CMD_C = "cmd_C";
const char* PARAM_CMD_D = "cmd_D";
const char* PARAM_CMD_T = "cmd_T";
const char* PARAM_VAL = "val";






bool wifiConfigRequired = false;
bool dhcp = true; // dhcp enable disble
bool con = false; // connection type wifi false

IPAddress IP;
IPAddress gateway;
IPAddress subnet;
IPAddress primaryDNS;
IPAddress secondaryDNS;


// Program state
enum state_t {
  S_RUN = 0,
  S_RUN_RUN,
  S_TOP_MENU_ITEMS,
  S_RUN_CQ,
  S_SET_SPEED_WPM,
  S_SET_OUTPUT_POWER,
  S_SET_KEYER_TYPE,
  S_SET_FREQ_OFFSET,
  S_SET_BUZZER_FREQ,
  S_SET_TEXT_GENERIC,
  S_WIFI_RECONNECT,
  S_RUN_BEACON,
  S_RUN_BEACON_HELL
} program_state;

enum set_text_state_t {
  S_SET_MY_CALL = 0,
  S_SET_WIFI_SSID,
  S_SET_WIFI_PWD
} set_text_state;


//
// for($i=-1;$i<13;$i++) { print $i+1 . " "; print 18.26+0.7*$i . " " . 10**((18.26+0.7*$i)/10). "\n"; }
// 0 17.56 57.0164272280748
// 1 18.26 66.9884609416526
// 2 18.96 78.7045789695099
// 3 19.66 92.4698173938223
// 4 20.36 108.642562361707
// 5 21.06 127.643880881134
// 6 21.76 149.968483550237
// 7 22.46 176.197604641163
// 8 23.16 207.014134879104
// 9 23.86 243.220400907382
// 10 24.56 285.759054337495
// 11 25.26 335.737614242955
// 12 25.96 394.457302075279
// 13 26.66 463.446919736288
//
#define PowerArrayMiliWatt_Size 6
//
// { Power_mW, Reg-setting }
const uint32_t PowerArrayMiliWatt [][2] = {
  {  0,  0 },   // 0mW = no output power, special case
  { 50,  0 },   // cca 50 mW
  { 100, 4 },   // cca 100 mW
  { 200, 8 },   // cca 200 mW
  { 330, 11 },  // cca 300 mW
  { 450, 13 }   // cca 450 mW
};
//
//
const char * TopMenuArray[] = {
  "1. << Back        ",
  "2. CQ...          ",
  "3. Set WPM        ",
  "4. Set Out Power  ",
  "5. Set Keyer Typ  ",
  "6. Set Offset Hz  ",
  "7. Set Buzzer Freq",
  "8. Set My Call    ",
  "9. Set WiFi SSID  ",
  "10. Set WiFi PWD  ",
  "11. WiFi Reconn.  ",
  "12. Beacon (vvv)  ",
  "13. Beacon FHELL  "
};
//
// Rotary Encoder structure
struct RotaryEncounters
{
  int32_t cntVal;
  int32_t cntMin;
  int32_t cntMax;
  int32_t cntIncr;
  int32_t cntValOld;
};

hw_timer_t * timer = NULL;
//TFT_eSPI     tft   = TFT_eSPI();  // Invoke library, pins defined in User_Setup.h
SX128XLT LT;                      // Create a library class instance called LT

uint8_t  rotaryA_Val = 0xFF;
uint8_t  rotaryB_Val = 0xFF;
uint8_t  ISR_cnt = 0;
uint8_t  cntIncrISR;
uint32_t loopCnt = 0;
uint32_t menuIndex;
uint32_t timeout_cnt = 0;
uint8_t  keyerVal      = 1;
uint8_t  pushBtnVal    = 1;
uint8_t  keyerDotPressed = 0;
uint8_t  keyerDashPressed = 0;
uint8_t  keyerCWstarted = 0;
uint8_t  pushBtnPressed = 0;
uint8_t  stop = 0;
uint32_t  tmp32a, tmp32b;

uint32_t FreqWord = 0;
uint32_t FreqWordNoOffset = 0;
uint32_t WPM_dot_delay;

char   freq_ascii_buf[20];   // Buffer for formatting of FREQ value
char   general_ascii_buf[40];
uint8_t general_ascii_buf_index = 0;
char   mycall_ascii_buf[40];
char   wifi_ssid_ascii_buf[40];
char   wifi_pwd_ascii_buf[40];
bool   params_set_by_udp_packet = false;

String s_mycall_ascii_buf;
//String s_wifi_ssid_ascii_buf;
//String s_wifi_pwd_ascii_buf;
String s_general_ascii_buf;
String udpdataString;

char   cq_message_buf[] =     "CQ CQ DE ";
char   cq_message_end_buf[] = " +K";
char   beacon_message_buf[] = "VVV  VVV  VVV  TEST  ";
char   eee_message_buf[] =    "E E E E E E E E E E E E E E E E E E E E E E E E E";

RotaryEncounters RotaryEnc_FreqWord;
RotaryEncounters RotaryEnc_MenuSelection;
RotaryEncounters RotaryEnc_KeyerSpeedWPM;
RotaryEncounters RotaryEnc_KeyerType;
RotaryEncounters RotaryEnc_OffsetHz;
RotaryEncounters RotaryEnc_BuzzerFreq;
RotaryEncounters RotaryEnc_OutPowerMiliWatt;
RotaryEncounters RotaryEnc_TextInput_Char_Index;
RotaryEncounters RotaryEncISR;

Preferences preferences;

// Copy values of variable pointed by r1 to RotaryEncISR variable
void RotaryEncPush(RotaryEncounters *r1) {
  RotaryEncISR = *r1;
  RotaryEncISR.cntValOld = RotaryEncISR.cntVal + 1;  // Make Old value different from actual in order to e.g. force initial update of display
}

// Copy values of RotaryEncISR variable to variable pointed by r1
void RotaryEncPop(RotaryEncounters *r1) {
  *r1 = RotaryEncISR;
}


// Display - Prepare box and cursor for main field
void display_mainfield_begin(uint8_t x) {
  display.setTextColor(WHITE);
  //display.clearDisplay();
  display.fillRect(1, 10, SCREEN_WIDTH - 2, 35, BLACK); // x, y, width, height
  display.setTextSize(1);
  display.setCursor(x, 25);
}

// Display - Prepare box and cursor for value field
void display_valuefield_begin () {
  display.fillRect(5, 43 - 2, SCREEN_WIDTH - 10, 12, WHITE); // x, y, width, height
  display.fillRect(6, 43 - 2 + 1, SCREEN_WIDTH - 10 - 2, 12 - 2, BLACK); // x, y, width, height
  display.setTextColor(WHITE);
  display.setTextSize(1);
  display.setCursor(20, 43);
  //display.fillRect(10,30,90,50,BLACK);
}

// Display - Clear the valuefield box
void display_valuefield_clear () {
  display.fillRect(5, 43 - 2, SCREEN_WIDTH - 10, 12, BLACK); // x, y, width, height
}

// Display - show values on status bar
void display_status_bar () {
  // Delete old info by drawing rectangle
  display.fillRect(0, SCREEN_HEIGHT - 9 - 9, SCREEN_WIDTH, 9 + 9, WHITE); // x, y, width, height
  display.fillRect(0, 0, SCREEN_WIDTH, 9, WHITE); // x, y, width, height
  //
  display.setTextColor(BLACK);
  display.setTextSize(1);
  //
  // Display MY_CALL, configured WPM (or Straight keyer) and configured power in mW
  display.setCursor(1, 1); // 7 is the font height
  display.print(s_mycall_ascii_buf);
  display.setCursor(52, 1); // 7 is the font height
  if (RotaryEnc_KeyerType.cntVal & 0x00000001) {
    display.print("Manual,");
  } else {
    display.print(RotaryEnc_KeyerSpeedWPM.cntVal);
    display.print("wpm, ");
  }
  display.print(PowerArrayMiliWatt[RotaryEnc_OutPowerMiliWatt.cntVal][0]);
  display.print("mW");
  // Display WiFi SSID and IP address
  display.setCursor(1, SCREEN_HEIGHT - 8 - 8); // 7 is the font height
  display.print(ssid.c_str());
  display.setCursor(1, SCREEN_HEIGHT - 8); // 7 is the font height
  display.print(IP);
  display.display();
}


// Limit values of RotaryEncISR.cntVal
void limitRotaryEncISR_values() {
  if (RotaryEncISR.cntVal >= RotaryEncISR.cntMax) {
    RotaryEncISR.cntVal = RotaryEncISR.cntMax;
  }
  if (RotaryEncISR.cntVal <= RotaryEncISR.cntMin) {
    RotaryEncISR.cntVal = RotaryEncISR.cntMin;
  }
}

// Calculate duration of DOT from WPM
void Calc_WPM_dot_delay ( uint32_t wpm) {
  WPM_dot_delay = (uint32_t) (double(1200.0) / (double) wpm);
}

// Send CW tone with duration duration_ms
/*
void sendCW(uint16_t duration_ms) {
  digitalWrite(LED1, LOW);
  ledcWriteTone(9, RotaryEnc_BuzzerFreq.cntVal);
  if (RotaryEnc_OutPowerMiliWatt.cntVal > 0) {
    LT.writeCommand(RADIO_SET_FS, 0, 0);
    LT.txEnable();
    LT.writeCommand(RADIO_SET_TXCONTINUOUSWAVE, 0, 0);
  }
  delay(duration_ms);
  ledcWriteTone(9, 0);
  if (RotaryEnc_OutPowerMiliWatt.cntVal > 0) {
    digitalWrite(LED1, HIGH);
    LT.setMode(MODE_STDBY_RC); // This should terminate TXCONTINUOUSWAVE
    LT.rxEnable();
  }
}
*/

//
// Refer to state diagram in page 57. - Figure 10-1: Transceiver Circuit Modes
//
// 1. Command SET_TXCONTINUOUSWAVE will get the TRX state machine to TX mode
// 2. Command SET_FS will get the TRX state machine to FS mode
//
// We should never go to STDBY mode since we want that PLL always runs
//
// Start CW - from FS to TX mode
void startCW() {
  digitalWrite(LED1, LOW);
  ledcWriteTone(9, RotaryEnc_BuzzerFreq.cntVal);
  //  LT.writeCommand(RADIO_SET_FS, 0, 0);
  //  LT.txEnable();
  if (RotaryEnc_OutPowerMiliWatt.cntVal > 0) {
    LT.writeCommand(RADIO_SET_TXCONTINUOUSWAVE, 0, 0);
  }
}

// Stop CW - from TX to FS mode
void stopCW() {
  digitalWrite(LED1, HIGH);
  ledcWriteTone(9, 0);
  if (RotaryEnc_OutPowerMiliWatt.cntVal > 0) {
    LT.writeCommand(RADIO_SET_FS, 0, 0);
  //LT.setMode(MODE_STDBY_RC); // This should terminate TXCONTINUOUSWAVE
  //LT.rxEnable();
  }
}

// Flash the LED
void led_Flash(uint16_t flashes, uint16_t delaymS)
{
  uint16_t index;
  for (index = 1; index <= flashes; index++)
  {
    digitalWrite(LED1, LOW);
    ledcWriteTone(9, RotaryEnc_BuzzerFreq.cntVal);
    delay(delaymS);
    ledcWriteTone(9, 0);
    digitalWrite(LED1, HIGH);
    delay(delaymS);
  }
}

//-----------------------------------------------------------------------------
// Encoding a character to Morse code and playing it
void morseEncode ( unsigned char rxd ) {
  uint8_t i, j, m, mask, morse_len;

  // rxd is already uppercase
  //if (rxd >= 97 && rxd < 123) {   // > 'a' && < 'z'
  //  rxd = rxd - 32;         // make the character uppercase
  //}
  //
  if ((rxd < 97) && (rxd > 12)) {   // above 96 no valid Morse characters
    m   = Morse_Coding_table[rxd - 32];
    morse_len = (m >> 5) & 0x07;
    mask = 0x10;
    if (morse_len >= 6) {
      morse_len = 6;
      mask = 0x20;
    }
    //
    for (i = 0; i < morse_len; i++) {
      startCW();
      if ((m & mask) > 0x00) { // Dash
        delay(WPM_dot_delay);
        delay(WPM_dot_delay);
        delay(WPM_dot_delay);
      } else { // Dot
        delay(WPM_dot_delay);
      }
      stopCW();
      // Dot-wait between played dot/dash
      delay(WPM_dot_delay);
      mask = mask >> 1;
    } //end for(i=0...
    // Dash-wait between characters
    delay(WPM_dot_delay);
    delay(WPM_dot_delay);
    delay(WPM_dot_delay);
    //
  } //if (rxd < 97...
}


void morseEncode2 ( uint8_t rxd ) {
  uint8_t i, j, m, mask, morse_len;

   rxd -= 128;
   morse_len = Morse_Coding_table2[rxd]>>8;
   m = Morse_Coding_table2[rxd] & 0xFF;
   mask = 1<<(morse_len-1);
   //
   for (i = 0; i < morse_len; i++) {
      startCW();
      if ((m & mask) > 0x00) { // Dash
        delay(WPM_dot_delay);
        delay(WPM_dot_delay);
        delay(WPM_dot_delay);
      } else { // Dot
        delay(WPM_dot_delay);
      }
      stopCW();
      // Dot-wait between played dot/dash
      delay(WPM_dot_delay);
      mask = mask >> 1;
    } //end for(i=0...
    // Dash-wait between characters
    delay(WPM_dot_delay);
    delay(WPM_dot_delay);
    delay(WPM_dot_delay);
    //
}


void notFound(AsyncWebServerRequest *request) {
  request->send(404, "text/plain", "Not found");
}

// process replacement in html pages
String processor(const String& var) {
  if (var == "FRQ_INDEX") {
    return String(RotaryEncISR.cntVal);
  }
  if (var == "MYCALL") {
    return s_mycall_ascii_buf;
  }
  if (var == "SPEED") {
    return sspeed;
  }
  if (var == "NETWORKS" ) {
    return wifiNetworkList;
  }


  if (var == "PWR" ) {
    String rsp;
    String pwst;
    int n = PowerArrayMiliWatt_Size;
    for (int i = 0; i < n; ++i) {
      pwst = String(PowerArrayMiliWatt[i][0]);
      rsp += "<option value=\"" + String(i) + "\" ";
      if (RotaryEnc_OutPowerMiliWatt.cntVal == i)  rsp += "SELECTED";
      rsp += ">" + pwst + "</option>";
    }
    return rsp;
  }



  if (var == "APIKEY") {
    return apikey;
  }

  if (var == "DHCP") {

    String rsp = "";
    if (dhcp) rsp = "checked";

    return  rsp;
  }


  if (var == "LOCALIP") {
    return sIP;
  }
  if (var == "SUBNET") {
    return sSubnet;
  }

  if (var == "GATEWAY") {
    return sGateway;
  }

  if (var == "PDNS") {
    return sPrimaryDNS;
  }
  if (var == "SDNS") {
    return sSecondaryDNS;
  }

  return String();
}

void savePrefs()
{
  //preferences.begin("my-app", false);    -- We assume this has been already called
  preferences.putString("ssid", ssid);
  preferences.putString("password", password);
  preferences.putString("apikey", apikey);
  preferences.putBool("dhcp", dhcp);
  preferences.putBool("con", con);
  preferences.getString("ip", sIP);
  preferences.getString("gateway", sGateway);
  preferences.getString("subnet", sSubnet);
  preferences.getString("pdns", sPrimaryDNS);
  preferences.getString("sdns", sSecondaryDNS);
  preferences.end();      // We can call preferences.end since after that we reboot

}

// Task SendMorse
void SendMorse_old_no_Queue ( void * parameter) {
  Serial.print("Send morse Task running on core ");
  Serial.println(xPortGetCoreID());
  for (;;) { //infinite loop
    if (message != "") {
      message.toUpperCase();
      int stri = message.length();
      for (int i = 0; i < stri; i++) {
        char c = message.charAt(i);
        if (c >= 128) {
         // if c >=128 we are sending non/defined morse characted which is encoded by Encode2 routine 
         morseEncode2(c);
        } else { 
         // Encoding of regular Morse character
         morseEncode(c);
        }
        if (stri < message.length()) {
          stri = message.length();
        }
      }
      message = "";
    }
    vTaskDelay(20);
  }
}

// Task SendMorse
void SendMorse ( void * parameter) {
  Serial.print("Send morse Task running on core ");
  Serial.println(xPortGetCoreID());
  char cc;
  for (;;) { //infinite loop
    if (xQueueReceive(queue, (void *)&cc, 0) == pdTRUE) {
        if (cc >= 128) {
         // if c >=128 we are sending undefined morse characted which is encoded by Encode2 routine 
         morseEncode2(cc);
        } else { 
         // Encoding of regular Morse character
         morseEncode(cc);
        }
    }
    vTaskDelay(15);
  }
}

// Send all characters in message String to Queue
void messageQueueSend() {
  message.toUpperCase();
  int stri = message.length();
  for (int i = 0; i < stri; i++) {
    char c = message.charAt(i);
    xQueueSend(queue, &c, 1000);
  }
}

void loop()
{
  //-----------------------------------------
  // -- Straight keyer
  if (RotaryEnc_KeyerType.cntVal & 0x00000001) {
    // Keyer pressed
    if ((keyerVal & 0x01) == 0)  {
      if (keyerCWstarted == 0) {
        startCW();
      }
      keyerCWstarted = 1;
      delay(10);
    }
    // Keyer released
    if ((keyerVal & 0x01 == 1) && (keyerCWstarted == 1)) {
      keyerCWstarted = 0;
      stopCW();
      delay(10);
    }
  } else {
    // -- Iambic keywer
    // Keyer pressed DOT
    if (((keyerVal & 0x01) == 0) || (keyerDotPressed == 1)) {
      startCW();
      delay(WPM_dot_delay);
      stopCW();
      delay(WPM_dot_delay>>1);
      ((keyerVal & 0x01) == 0) ? keyerDotPressed  = 1 : keyerDotPressed = 0;
      ((keyerVal & 0x02) == 0) ? keyerDashPressed = 1 : keyerDashPressed = 0;
      delay(WPM_dot_delay>>1);
    }
    // Keyer pressed DASH
    if (((keyerVal & 0x02) == 0) || (keyerDashPressed == 1)) {
      startCW();
      delay(WPM_dot_delay);
      delay(WPM_dot_delay);
      delay(WPM_dot_delay);
      stopCW();
      delay(WPM_dot_delay>>1);
      ((keyerVal & 0x01) == 0) ? keyerDotPressed  = 1 : keyerDotPressed = 0;
      ((keyerVal & 0x02) == 0) ? keyerDashPressed = 1 : keyerDashPressed = 0;
      delay(WPM_dot_delay>>1);
    }
  }
  // Process timeout for display items other than main screen
  if (program_state != S_RUN_RUN) {
    if (timeout_cnt > 6000) {
      display_valuefield_clear();
      display_valuefield_begin();
      display.print("Timeout...");
      display.display();
      delay(600);
      timeout_cnt = 0;
      RotaryEncPush(&RotaryEnc_FreqWord);
      program_state = S_RUN;
    }
  }
  //
  // Main FSM
  //-----------------------------------------
  switch (program_state) {
    //--------------------------------
    case S_RUN:
      timeout_cnt = 0;
      display_valuefield_clear();
      program_state = S_RUN_RUN;
      break;
    //--------------------------------
    case S_RUN_RUN:
      timeout_cnt = 0;
      // Update display with Frequency info when it has changed
      if (RotaryEncISR.cntVal != RotaryEncISR.cntValOld) {
        limitRotaryEncISR_values();
        display_mainfield_begin(23);
        format_freq(RegWordToFreq(RotaryEncISR.cntVal), freq_ascii_buf, params_set_by_udp_packet);
        params_set_by_udp_packet = false;
        display.print(freq_ascii_buf);
        display.display();
        JUsetRfFrequency(RegWordToFreq(RotaryEncISR.cntVal), RotaryEnc_OffsetHz.cntVal);
        display_status_bar();
      }
      RotaryEncISR.cntValOld = RotaryEncISR.cntVal;
      // This has to be at very end since with RotaryEncPush we are making RotaryEncISR.cntValOld different from RotaryEncISR.cntVal
      if (pushBtnVal == PUSH_BTN_PRESSED) {
        WAIT_Push_Btn_Release(200);
        program_state = S_TOP_MENU_ITEMS;
        RotaryEncPop(&RotaryEnc_FreqWord);
        RotaryEncPush(&RotaryEnc_MenuSelection);
      }
      break;
    //--------------------------------
    case S_TOP_MENU_ITEMS:
      // Wrap aroud
      menuIndex = RotaryEncISR.cntVal % (sizeof(TopMenuArray) / sizeof(TopMenuArray[0]));
      // Update display if there is change
      if (RotaryEncISR.cntVal != RotaryEncISR.cntValOld) {
        timeout_cnt = 0;
        display_mainfield_begin(10);
        display.print(TopMenuArray[menuIndex]);
        display.display();
      }
      RotaryEncISR.cntValOld = RotaryEncISR.cntVal;
      // Decide into which menu item to go based on selection
      if (pushBtnVal == PUSH_BTN_PRESSED) {
        WAIT_Push_Btn_Release(200);
        RotaryEncPop(&RotaryEnc_MenuSelection);
        switch (menuIndex) {
          // -----------------------------
          case 0:
            program_state = S_RUN;
            RotaryEncPush(&RotaryEnc_FreqWord); // makes RotaryEncISR.cntValOld different from RotaryEncISR.cntVal  ==> forces display update
            break;
          // -----------------------------
          case 1:
            program_state = S_RUN_CQ;
            display_valuefield_begin();
            display.print("CQ...");
            display.display();
            break;
          // -----------------------------
          case 2:
            program_state = S_SET_SPEED_WPM;
            RotaryEncPush(&RotaryEnc_KeyerSpeedWPM); // makes RotaryEncISR.cntValOld different from RotaryEncISR.cntVal  ==> forces display update
            break;
          // -----------------------------
          case 3:
            program_state = S_SET_OUTPUT_POWER;
            RotaryEncPush(&RotaryEnc_OutPowerMiliWatt); // makes RotaryEncISR.cntValOld different from RotaryEncISR.cntVal  ==> forces display update
            break;
          // -----------------------------
          case 4:
            program_state = S_SET_KEYER_TYPE;
            RotaryEncPush(&RotaryEnc_KeyerType); // makes RotaryEncISR.cntValOld different from RotaryEncISR.cntVal  ==> forces display update
            break;
          // -----------------------------
          case 5:
            program_state = S_SET_FREQ_OFFSET;
            RotaryEncPush(&RotaryEnc_OffsetHz); // makes RotaryEncISR.cntValOld different from RotaryEncISR.cntVal  ==> forces display update
            break;
          // -----------------------------
          case 6:
            program_state = S_SET_BUZZER_FREQ;
            RotaryEncPush(&RotaryEnc_BuzzerFreq); // makes RotaryEncISR.cntValOld different from RotaryEncISR.cntVal  ==> forces display update
            break;
          // -----------------------------
          case 7:
            program_state  = S_SET_TEXT_GENERIC;
            set_text_state = S_SET_MY_CALL;
            s_general_ascii_buf = s_mycall_ascii_buf.substring(0);
            RotaryEncPush(&RotaryEnc_TextInput_Char_Index);
            RotaryEncISR.cntVal = s_general_ascii_buf[0];
            general_ascii_buf_index = 0;
            break;
          // -----------------------------
          case 8:
            program_state  = S_SET_TEXT_GENERIC;
            set_text_state = S_SET_WIFI_SSID;
            //s_general_ascii_buf = s_wifi_ssid_ascii_buf.substring(0);
            s_general_ascii_buf = ssid.substring(0);
            RotaryEncPush(&RotaryEnc_TextInput_Char_Index);
            RotaryEncISR.cntVal = s_general_ascii_buf[0];
            general_ascii_buf_index = 0;
            break;
          // -----------------------------
          case 9:
            program_state  = S_SET_TEXT_GENERIC;
            set_text_state = S_SET_WIFI_PWD;
            //s_general_ascii_buf = s_wifi_pwd_ascii_buf.substring(0);
            s_general_ascii_buf = password.substring(0);
            RotaryEncPush(&RotaryEnc_TextInput_Char_Index);
            RotaryEncISR.cntVal = s_general_ascii_buf[0];
            general_ascii_buf_index = 0;
            break;
          // -----------------------------
          case 10:
            program_state = S_WIFI_RECONNECT;
            break;
          // -----------------------------
          case 11:
            program_state = S_RUN_BEACON;
            display_valuefield_begin();
            display.print("BEACON...");
            display.display();
            break;
          // -----------------------------
           case 12:
            program_state = S_RUN_BEACON_HELL;
            display_valuefield_begin();
            display.print("FHELL BEACON");
            display.display();
            break;
          // -----------------------------
          default:
            program_state = S_RUN;
            break;
        }
      }
      break;
    //--------------------------------
    case S_RUN_CQ:
      stop = 0;
      for (int j = 0; (j < 3) && !stop; j++) {
        // CQ
        for (int i = 0; (i < sizeof(cq_message_buf)) && !stop; i++) {
          morseEncode(cq_message_buf[i]);
          timeout_cnt = 0; // do not allow to timeout this operation
          if (pushBtnVal == PUSH_BTN_PRESSED) {
            stop++;
          }
        }
        // My Call
        for (int i = 0; (i < s_mycall_ascii_buf.length()) && !stop; i++) {
          morseEncode(s_mycall_ascii_buf[i]);
          timeout_cnt = 0; // do not allow to timeout this operation
          if (pushBtnVal == PUSH_BTN_PRESSED) {
            stop++;
          }
        }
        //
        morseEncode(' ');
        // My Call
        for (int i = 0; (i < s_mycall_ascii_buf.length()) && !stop; i++) {
          morseEncode(s_mycall_ascii_buf[i]);
          timeout_cnt = 0; // do not allow to timeout this operation
          if (pushBtnVal == PUSH_BTN_PRESSED) {
            stop++;
          }
        }
      } // j
      // +K
      for (int i = 0; (i < sizeof(cq_message_end_buf)) && !stop; i++) {
        morseEncode(cq_message_end_buf[i]);
        timeout_cnt = 0; // do not allow to timeout this operation
        if (pushBtnVal == PUSH_BTN_PRESSED) {
          stop++;
        }
      }
      //
      WAIT_Push_Btn_Release(200);
      RotaryEncPush(&RotaryEnc_FreqWord);
      program_state = S_RUN;
      display.display();
      break;
    //--------------------------------
    case S_SET_SPEED_WPM:
      if (RotaryEncISR.cntVal != RotaryEncISR.cntValOld) {
        timeout_cnt = 0;
        limitRotaryEncISR_values();
        display_valuefield_begin();
        display.print(RotaryEncISR.cntVal);
        display.display();
        Calc_WPM_dot_delay(RotaryEncISR.cntVal);  // this will set the WPM_dot_delay variable
      }
      RotaryEncISR.cntValOld = RotaryEncISR.cntVal;
      if (pushBtnVal == PUSH_BTN_PRESSED) {
        WAIT_Push_Btn_Release(200);
        speed = RotaryEncISR.cntVal;
        sspeed = String(speed);
        preferences.putInt("KeyerWPM", RotaryEncISR.cntVal);
        RotaryEncPop(&RotaryEnc_KeyerSpeedWPM);
        RotaryEncPush(&RotaryEnc_FreqWord);
        program_state = S_RUN;
      }
      break;
    //--------------------------------
    case S_SET_OUTPUT_POWER:
      if (RotaryEncISR.cntVal != RotaryEncISR.cntValOld) {
        timeout_cnt = 0;
        limitRotaryEncISR_values();
        display_valuefield_begin();
        //RotaryEncISR.cntVal = RotaryEncISR.cntVal % (sizeof(PowerArrayMiliWatt) / sizeof(uint32_t)); // safe
        RotaryEncISR.cntVal = RotaryEncISR.cntVal % PowerArrayMiliWatt_Size;
        display.print(PowerArrayMiliWatt[RotaryEncISR.cntVal][0]);
        display.print(" mW    ");
        display.display();
        LT.setTxParams(PowerArrayMiliWatt[RotaryEncISR.cntVal][1], RADIO_RAMP_10_US);
      }
      RotaryEncISR.cntValOld = RotaryEncISR.cntVal;
      if (pushBtnVal == PUSH_BTN_PRESSED) {
        WAIT_Push_Btn_Release(200);
        preferences.putInt("OutPower", RotaryEncISR.cntVal);
        RotaryEncPop(&RotaryEnc_OutPowerMiliWatt);
        RotaryEncPush(&RotaryEnc_FreqWord);
        program_state = S_RUN;
      }
      break;
    //--------------------------------
    case S_SET_KEYER_TYPE:
      if (RotaryEncISR.cntVal != RotaryEncISR.cntValOld) {
        timeout_cnt = 0;
        display_valuefield_begin();
        display.print(RotaryEncISR.cntVal % 2 ?  "Straight  " : "Iambic    ");
        display.display();
      }
      RotaryEncISR.cntValOld = RotaryEncISR.cntVal;
      //
      if (pushBtnVal == PUSH_BTN_PRESSED) {
        WAIT_Push_Btn_Release(200);
        preferences.putInt("KeyerType", RotaryEncISR.cntVal);
        RotaryEncPop(&RotaryEnc_KeyerType);
        RotaryEncPush(&RotaryEnc_FreqWord);
        program_state = S_RUN;
      }
      break;
    //--------------------------------
    case S_SET_FREQ_OFFSET:
      if (RotaryEncISR.cntVal != RotaryEncISR.cntValOld) {
        timeout_cnt = 0;
        limitRotaryEncISR_values();
        JUsetRfFrequency(RegWordToFreq(RotaryEncISR.cntVal), RotaryEncISR.cntVal);  // Offset
        display_valuefield_begin();
        display.print(RotaryEncISR.cntVal);
        display.display();
      }
      RotaryEncISR.cntValOld = RotaryEncISR.cntVal;
      //
      if (pushBtnVal == PUSH_BTN_PRESSED) {
        WAIT_Push_Btn_Release(200);
        preferences.putInt("OffsetHz", RotaryEncISR.cntVal);
        RotaryEncPop(&RotaryEnc_OffsetHz);
        RotaryEncPush(&RotaryEnc_FreqWord);
        program_state = S_RUN;
      }
      break;

    //--------------------------------
    case S_SET_BUZZER_FREQ:
      if (RotaryEncISR.cntVal != RotaryEncISR.cntValOld) {
        timeout_cnt = 0;
        display_valuefield_begin();
        display.print(RotaryEncISR.cntVal);
        display.display();
        // Short beep with new tone value
        ledcWriteTone(9, RotaryEncISR.cntVal);
        delay(100);
        ledcWriteTone(9, 0);
      }
      RotaryEncISR.cntValOld = RotaryEncISR.cntVal;
      //
      if (pushBtnVal == PUSH_BTN_PRESSED) {
        WAIT_Push_Btn_Release(200);
        preferences.putInt("BuzzerFreq", RotaryEncISR.cntVal);
        RotaryEncPop(&RotaryEnc_BuzzerFreq);
        RotaryEncPush(&RotaryEnc_FreqWord);
        program_state = S_RUN;
      }
      break;
    //--------------------------------
    case S_SET_TEXT_GENERIC:
      // Reset timeout_cnt when there is activity with encoder
      if (RotaryEncISR.cntVal != RotaryEncISR.cntValOld) {
        timeout_cnt = 0;
      }
      limitRotaryEncISR_values();
      display_valuefield_begin();
      // Blinking effect on selected character
      if (loopCnt % 2) {
        s_general_ascii_buf[general_ascii_buf_index] = RotaryEncISR.cntVal;
      } else {
        s_general_ascii_buf[general_ascii_buf_index] = ' ';
      }
      display.print(s_general_ascii_buf);
      display.display();
      // Set it back to valid character after displaying
      s_general_ascii_buf[general_ascii_buf_index] = RotaryEncISR.cntVal;
      //}
      RotaryEncISR.cntValOld = RotaryEncISR.cntVal;
      delay(150);
      //
      // With pushbutton pressed either go to next character of finish if selected character was decimal 127 = ⌂ (looks like house icon with roof)
      if (pushBtnVal == PUSH_BTN_PRESSED) {
        timeout_cnt = 0;
        WAIT_Push_Btn_Release(200);
        // 127 = End of string
        if (RotaryEncISR.cntVal == 127) {
          s_general_ascii_buf[general_ascii_buf_index] = 0;  // Terminate string with null
          switch (set_text_state) {
            //---------------------
            case S_SET_MY_CALL:
              preferences.putString("MyCall", s_general_ascii_buf);
              s_mycall_ascii_buf = s_general_ascii_buf.substring(0);
              break;
            //---------------------
            case S_SET_WIFI_SSID:
              preferences.putString("ssid", s_general_ascii_buf);
              //s_wifi_ssid_ascii_buf = s_general_ascii_buf.substring(0);
              ssid = s_general_ascii_buf.substring(0);
              break;
            //---------------------
            case S_SET_WIFI_PWD:
              preferences.putString("password", s_general_ascii_buf);
              //s_wifi_pwd_ascii_buf = s_general_ascii_buf.substring(0);
              password = s_general_ascii_buf.substring(0);
              break;
            //---------------------
            default:
              break;
          }
          RotaryEncPush(&RotaryEnc_FreqWord);
          program_state = S_RUN;
        } else {
          general_ascii_buf_index++;
          if (general_ascii_buf_index >= s_general_ascii_buf.length()) {
            s_general_ascii_buf += RotaryEncISR.cntVal;;
            RotaryEncISR.cntVal = s_general_ascii_buf[general_ascii_buf_index];
          } else {
            RotaryEncISR.cntVal = s_general_ascii_buf[general_ascii_buf_index];
          }
          RotaryEncISR.cntValOld = RotaryEncISR.cntVal + 1;   // Force display update in next cycle
        }
      }
      break;
    //--------------------------------
    case S_WIFI_RECONNECT:
      ESP.restart();  // just restart the board
      break;
    //--------------------------------
    case S_RUN_BEACON:
      //
      for (int j = 0; j < 10; j++) {
        pushBtnPressed = 0;
        for (int i = 0; i < sizeof(beacon_message_buf); i++) {
          morseEncode(beacon_message_buf[i]);
          timeout_cnt = 0; // do not allow to timeout this operation
          if (pushBtnVal == PUSH_BTN_PRESSED) {
            pushBtnPressed = 1;
            break;
          }
        }
        if (pushBtnPressed != 0) break;
      }
      //if (pushBtnPressed) {
      WAIT_Push_Btn_Release(200);
      RotaryEncPush(&RotaryEnc_FreqWord);
      display_valuefield_begin();
      display.display();
      program_state = S_RUN;
      //}
      break;
     //--------------------------------
    case S_RUN_BEACON_HELL:
      //
      for (int j = 0; j < 10; j++) {
        pushBtnPressed = 0;
        encode_hell("VVVV  TEST");
        if (pushBtnVal == PUSH_BTN_PRESSED) {
          pushBtnPressed = 1;
          break;
        }
      }
      WAIT_Push_Btn_Release(200);
      RotaryEncPush(&RotaryEnc_FreqWord);
      display_valuefield_begin();
      display.display();
      program_state = S_RUN;
      break;
    //--------------------------------
    default:
      break;
  } // switch program_state

  loopCnt++;

}  // loop



void IRAM_ATTR onTimer() {
  //portENTER_CRITICAL_ISR(&timerMux);
  //interruptCounter++;
  //digitalWrite(LED_PIN,LEDtoggle);
  //LEDtoggle = !LEDtoggle;
  //portEXIT_CRITICAL_ISR(&timerMux);

  uint32_t incr_val;
  //
  timeout_cnt++;
  //
  if (ISR_cnt != 255) ISR_cnt++;
  //
  keyerVal   = digitalRead(KEYER_DASH) << 1 | digitalRead(KEYER_DOT);
  pushBtnVal = digitalRead(ROTARY_ENC_PUSH);
  // SW debounce
  rotaryA_Val = (rotaryA_Val << 1 | (uint8_t)digitalRead(ROTARY_ENC_A)) & 0x0F;
  //
  // Rising edge --> 0001
  if (rotaryA_Val == 0x01) {
    rotaryB_Val = digitalRead(ROTARY_ENC_B);
    // Rotation speedup
    (ISR_cnt <= 12) ? cntIncrISR = RotaryEncISR.cntIncr << 4 : cntIncrISR = RotaryEncISR.cntIncr;
    ISR_cnt = 0;
    //
    if (rotaryB_Val == 0) {
      RotaryEncISR.cntVal += cntIncrISR;
      //RotaryEncISR.cntVal = RotaryEncISR.cntVal + cntIncrISR;
    } else {
      RotaryEncISR.cntVal -= cntIncrISR;
      //RotaryEncISR.cntVal = RotaryEncISR.cntVal - cntIncrISR;
    }
  }


}


void setup() {

  if (!SPIFFS.begin()) {
    Serial.println("An Error has occurred while mounting SPIFFS");
    return;
  }

  pinMode(ROTARY_ENC_A,    INPUT_PULLUP);
  pinMode(ROTARY_ENC_B,    INPUT_PULLUP);
  pinMode(ROTARY_ENC_PUSH, INPUT_PULLUP);
  pinMode(KEYER_DOT,       INPUT_PULLUP);
  pinMode(KEYER_DASH,      INPUT_PULLUP);
  pinMode(TCXO_EN, OUTPUT);
  digitalWrite(TCXO_EN, 1);
  pinMode(LED1, OUTPUT);                                   //setup pin as output for indicator LED
  //
  // Configure BUZZER functionalities.
  ledcSetup(9, 8000, 8);   //PWM Channel, Freq, Resolution
  /// Attach BUZZER pin.
  ledcAttachPin(BUZZER, 9); // Pin, Channel

  // Timer for ISR which is processing rotary encoder events
  timer = timerBegin(0, 80, true);
  timerAttachInterrupt(timer, &onTimer, true);
  timerAlarmWrite(timer, 2500, true);  // 2500 = 2.5 msec
  timerAlarmEnable(timer);

  RotaryEnc_FreqWord.cntVal  = FreqToRegWord(Frequency);
  RotaryEnc_FreqWord.cntMin  = FreqToRegWord(2400000000);
  RotaryEnc_FreqWord.cntMax  = FreqToRegWord(2400500000);
  RotaryEnc_FreqWord.cntIncr = 1;

  // With MenuSelection we start counter at high value around 1 milion so that we can count up/down
  // The weird formula below using ...sizeof(TopMenuArray)... will just make sure that initial menu is at index 1 = "CQ..."
  RotaryEnc_MenuSelection    = { int(1000000/(sizeof(TopMenuArray) / sizeof(TopMenuArray[0]))) * (sizeof(TopMenuArray) / sizeof(TopMenuArray[0])) + 1, 0, 2000000, 1, 0}; 
  //
  RotaryEnc_KeyerSpeedWPM    = {20, 10, 40, 1, 0};
  RotaryEnc_KeyerType        = {1000000, 0, 2000000, 1, 0};   // We will implement modulo
  RotaryEnc_OffsetHz         = {Offset, -100000, 100000, 100, 0};
  RotaryEnc_BuzzerFreq       = {600, 0, 2000, 100, 0};
  RotaryEnc_OutPowerMiliWatt = {PowerArrayMiliWatt_Size - 1, 0, PowerArrayMiliWatt_Size - 1, 1, 0};
  RotaryEnc_TextInput_Char_Index  = {65, 33, 127, 1, 66};



  // Get configuration values stored in EEPROM/FLASH
  preferences.begin("my-app", false);   // false = RW mode
  // Get the counter value, if the key does not exist, return a default value of XY
  // Note: Key name is limited to 15 chars.
  RotaryEnc_KeyerSpeedWPM.cntVal    = preferences.getInt("KeyerWPM", 20);
  speed = RotaryEnc_KeyerSpeedWPM.cntVal;
  sspeed = String(speed);
  Calc_WPM_dot_delay(RotaryEnc_KeyerSpeedWPM.cntVal);
  RotaryEnc_KeyerType.cntVal        = preferences.getInt("KeyerType", 0);
  RotaryEnc_OffsetHz.cntVal         = preferences.getInt("OffsetHz", 0);
  RotaryEnc_BuzzerFreq.cntVal       = preferences.getInt("BuzzerFreq", 600);
  RotaryEnc_OutPowerMiliWatt.cntVal = preferences.getInt("OutPower", PowerArrayMiliWatt_Size - 1); // Max output power

  s_mycall_ascii_buf                  = preferences.getString("MyCall", "CALL???");
  //s_wifi_ssid_ascii_buf               = preferences.getString("ssid", "SSID??");
  //s_wifi_pwd_ascii_buf                = preferences.getString("password",  "PWD???");

  dhcp = preferences.getBool("dhcp", 1);
  con  = preferences.getBool("con", 0);
  ssid = preferences.getString("ssid");
  password = preferences.getString("password");
  apikey = preferences.getString("apikey", "1111");
  sIP        = preferences.getString("ip", "192.168.1.200");
  sGateway   = preferences.getString("gateway", "192.168.1.1");
  sSubnet    = preferences.getString("subnet", "255.255.255.0");
  sPrimaryDNS = preferences.getString("pdns", "8.8.8.8");
  sSecondaryDNS = preferences.getString("sdns", "8.8.4.4");

  //preferences.end();   -- do not call prefs.end since we assume writing to NV memory later in application

  RotaryEncPush(&RotaryEnc_FreqWord);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) { // Address 0x3D for 128x64
    Serial.println(F("SSD1306 allocation failed"));
    //for(;;); // Don't proceed, loop forever
  }


  // Initial splash screen
  display.clearDisplay();
  display.fillRect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, BLACK); // x, y, width, height
  display.setTextSize(1);
  display.setTextColor(WHITE);
  display.setCursor(1, 10);
  display.println(" QO-100 CW TX 2.4GHz");
  display.setCursor(7, 20);
  display.println("by OK1CDJ and OM2JU");
  display.setCursor(13, 35);
  display.println("http://hamshop.cz");
  display.setCursor(10, 50);
  display.println("Starting WiFi...");
  display.drawFastVLine(0, 0, SCREEN_HEIGHT, WHITE);
  display.drawFastVLine(SCREEN_WIDTH - 1, 0, SCREEN_HEIGHT, WHITE);
  display.drawFastHLine(0, 0, SCREEN_WIDTH, WHITE);
  display.drawFastHLine(0, SCREEN_HEIGHT - 1, SCREEN_WIDTH, WHITE);
  display.display();
  delay(500);

  //led_Flash(2, 125);                                       //two quick LED flashes to indicate program start

  Serial.begin(115200);
  Serial.println();
  Serial.print(F(__TIME__));
  Serial.print(F(" "));
  Serial.println(F(__DATE__));
  Serial.println();
  Serial.println(F(Program_Version));
  Serial.println();
  Serial.println();

  //SPI.begin();
  SPI.begin(SCK, MISO, MOSI, NSS);
  Serial.println(F("SPI OK..."));

  //SPI beginTranscation is normally part of library routines, but if it is disabled in library
  //a single instance is needed here, so uncomment the program line below
  //SPI.beginTransaction(SPISettings(8000000, MSBFIRST, SPI_MODE0));

  //setup hardware pins used by device, then check if device is found
  if (LT.begin(NSS, NRESET, RFBUSY, DIO1, DIO2, DIO3, RX_EN, TX_EN, LORA_DEVICE))  {
    Serial.println(F("LoRa Device found"));
    led_Flash(1, 50);
    delay(30);
    led_Flash(1, 50 * 3);
    led_Flash(1, 50);
  } else {
    Serial.println(F("No device responding"));
    while (1) {
      led_Flash(50, 50);  //long fast speed LED flash indicates device error
    }
  }

  //The function call list below shows the complete setup for the LoRa device using the information defined in the
  //Settings.h file.
  //The 'Setup LoRa device' list below can be replaced with a single function call;
  //LT.setupLoRa(Frequency, Offset, SpreadingFactor, Bandwidth, CodeRate);


  //***************************************************************************************************
  //Setup LoRa device
  //***************************************************************************************************
  LT.setMode(MODE_STDBY_RC);
  LT.setRegulatorMode(USE_LDO);
  LT.setPacketType(PACKET_TYPE_GFSK);
  JUsetRfFrequency(Frequency, Offset);
  LT.setBufferBaseAddress(0, 0);
  LT.setModulationParams(SpreadingFactor, Bandwidth, CodeRate);
  LT.setPacketParams(12, LORA_PACKET_VARIABLE_LENGTH, 255, LORA_CRC_ON, LORA_IQ_NORMAL, 0, 0);
  //LT.setModulationParams(GFS_BLE_BR_0_125_BW_0_3, GFS_BLE_MOD_IND_0_35, BT_0_5);
  LT.setTxParams(TXpower, RADIO_RAMP_10_US);
  //LT.setDioIrqParams(IRQ_RADIO_ALL, (IRQ_TX_DONE + IRQ_RX_TX_TIMEOUT), 0, 0);
  LT.setDioIrqParams(IRQ_RADIO_NONE, 0, 0, 0);
  //***************************************************************************************************

  LT.txEnable();  //This will stay alway ON as we transmit only


  Serial.println();
  LT.printModemSettings();                               //reads and prints the configured LoRa settings, useful check
  Serial.println();
  LT.printOperatingSettings();                           //reads and prints the configured operating settings, useful check
  Serial.println();
  Serial.println();
  LT.printRegisters(0x900, 0x9FF);                       //print contents of device registers, normally 0x900 to 0x9FF
  Serial.println();
  Serial.println();

  Serial.print(F("Transmitter ready"));
  Serial.println();

  LT.setTxParams(PowerArrayMiliWatt[RotaryEnc_OutPowerMiliWatt.cntVal][1], RADIO_RAMP_10_US);

  //
  queue = xQueueCreate( 512, sizeof( char ) );
  xTaskCreatePinnedToCore(SendMorse, "Task1", 20000, NULL, 1, NULL,  0);



  Serial.println(RegWordToFreq(RotaryEncISR.cntVal));

  //Scan for WIFI networks before config to avoid reset when it takes long time...
  Serial.println(F("Scanning for WIFI..."));
  int n = WiFi.scanNetworks();
  for (int i = 0; i < n; ++i) {
    Serial.println(WiFi.SSID(i) + ' ' + WiFi.RSSI(i));
    wifiNetworkList += "<option value=\"" + WiFi.SSID(i) + "\">" + WiFi.SSID(i) + " (RSSI: " + WiFi.RSSI(i) + ")</option>";
  }
  Serial.println(F("Done."));
  // Try connect to WIFI
  if (!wifiConfigRequired)
  {
    WiFi.mode(WIFI_STA);
    Serial.println("Trying connect to " + ssid);
    WiFi.begin(ssid.c_str(), password.c_str());
    if (WiFi.waitForConnectResult() != WL_CONNECTED) {
      Serial.printf("WiFi Failed!\n");
      WiFi.disconnect();
      wifiConfigRequired = true;
    }
    if (!wifiConfigRequired) {
      Serial.print("WIFI IP Address: ");
      IP = WiFi.localIP();
      Serial.println(IP);
    }
  }

  // not connected and make AP
  if (wifiConfigRequired) {

    wifiConfigRequired = true;
    Serial.println("Start AP");
    Serial.printf("WiFi is not connected or configured. Starting AP mode\n");
    ssid = "QO100TX";
    WiFi.softAP(ssid.c_str());
    IP = WiFi.softAPIP();
    Serial.printf("SSID: %s, IP: ", ssid.c_str());
    Serial.println(IP);
  }


  server.on("/", HTTP_GET, [](AsyncWebServerRequest * request) {

    if ((request->hasParam(PARAM_APIKEY) && request->getParam(PARAM_APIKEY)->value() == apikey) || wifiConfigRequired) {
      // Freq. Index
      if (request->hasParam(PARAM_FRQ_INDEX)) {
        sfreq = request->getParam(PARAM_FRQ_INDEX)->value();
        RotaryEncISR.cntVal = sfreq.toInt();
        Serial.print("Freq changed: ");
        Serial.println(sfreq);
        RotaryEncISR.cntValOld++;   // Change Old value in order to force display update
        program_state = S_RUN;
      }
      // Speed WPM
      if (request->hasParam(PARAM_SPEED)) {
        sspeed = request->getParam(PARAM_SPEED)->value();
        speed = sspeed.toInt();
        RotaryEnc_KeyerSpeedWPM.cntVal = speed;
        Calc_WPM_dot_delay (speed);
        program_state = S_RUN;
        RotaryEncISR.cntValOld++;   // Change Old value in order to force display update
      }
      // Output Power
      if (request->hasParam(PARAM_PWR)) {
        spwr = request->getParam(PARAM_PWR)->value();
        Serial.print("Power changed: ");
        Serial.println(spwr);
        RotaryEnc_OutPowerMiliWatt.cntVal = spwr.toInt();
        LT.setTxParams(PowerArrayMiliWatt[RotaryEnc_OutPowerMiliWatt.cntVal][1], RADIO_RAMP_10_US);
        RotaryEncISR.cntValOld++;   // Change Old value in order to force display update
        program_state = S_RUN;
      }
      // Message
      if (request->hasParam(PARAM_MESSAGE)) {
        message = " ";
        message += request->getParam(PARAM_MESSAGE)->value();
        messageQueueSend();
      }
      // Break
      if (request->hasParam(PARAM_CMD_B)) {
        scmd = request->getParam(PARAM_CMD_B)->value();
        if (scmd.charAt(0) == 'B') {
          xQueueReset( queue );
          stopCW();  // Just in case we were sending some carrier
        }
      }
      // CQ
      if (request->hasParam(PARAM_CMD_C)) {
        scmd = request->getParam(PARAM_CMD_C)->value();
        if (scmd.charAt(0) == 'C') {
          message = " ";
          message += cq_message_buf;
          message += s_mycall_ascii_buf;
          message += message;
          message += cq_message_end_buf;
          messageQueueSend();
        }
      }
      // DOTS
      if (request->hasParam(PARAM_CMD_D)) {
        scmd = request->getParam(PARAM_CMD_D)->value();
        if (scmd.charAt(0) == 'D') {
          message = " ";
          message += eee_message_buf;
          messageQueueSend();
        }
      }
      // Tune
      if (request->hasParam(PARAM_CMD_T)) {
        scmd = request->getParam(PARAM_CMD_T)->value();
        if (scmd.charAt(0) == 'T') {
          startCW();
          delay(3000);
          stopCW();
        }
      }      

      request->send(SPIFFS, "/index.html", String(), false,   processor);

    }
    else {
      request->send(401, "text/plain", "Unauthorized");
    }
  });


  server.on("/update", HTTP_GET, [](AsyncWebServerRequest * request) {

    if ((request->hasParam(PARAM_APIKEY) && request->getParam(PARAM_APIKEY)->value() == apikey) || wifiConfigRequired) {

      request->send(SPIFFS, "/update.html", String(), false,   processor);
    }
    else {
      request->send(401, "text/plain", "Unauthorized");
    }
  });

 server.on("/frq", HTTP_GET, [](AsyncWebServerRequest * request) {

    if ((request->hasParam(PARAM_APIKEY) && request->getParam(PARAM_APIKEY)->value() == apikey) || wifiConfigRequired) {

       if (request->hasParam(PARAM_VAL)) {
        sfreq = request->getParam(PARAM_VAL)->value();
        RotaryEncISR.cntVal = sfreq.toInt();
        Serial.print("Freq changed: ");
        Serial.println(sfreq);
        RotaryEncISR.cntValOld++;   // Change Old value in order to force display update
        program_state = S_RUN;
        request->send(200, "text/plain", "OK");
      }

     // request->send(SPIFFS, "/update.html", String(), false,   processor);
    }
    else {
      request->send(401, "text/plain", "Unauthorized");
    }
  });


  server.on("/cfg", HTTP_GET, [](AsyncWebServerRequest * request)
  {
    if ((request->hasParam(PARAM_APIKEY) && request->getParam(PARAM_APIKEY)->value() == apikey) || wifiConfigRequired) {

      request->send(SPIFFS, "/cfg.html", String(), false,   processor);
    } else request->send(401, "text/plain", "Unauthorized");
  });
  server.on("/cfg-save", HTTP_GET, [](AsyncWebServerRequest * request)
  {
    if (request->hasParam("ssid") && request->hasParam("password") && request->hasParam("apikey")) {
      ssid = request->getParam(PARAM_SSID)->value();
      if (request->getParam(PARAM_PASSWORD)->value() != NULL) password = request->getParam(PARAM_PASSWORD)->value();
      apikey = request->getParam(PARAM_APIKEY)->value();

      if (request->hasParam("dhcp")) dhcp = true; else dhcp = false;
      if (request->hasParam("localip")) sIP = request->getParam(PARAM_LOCALIP)->value();
      if (request->hasParam("gateway")) sGateway   = request->getParam(PARAM_GATEWAY)->value();
      if (request->hasParam("subnet")) sSubnet    = request->getParam(PARAM_SUBNET)->value();
      if (request->hasParam("pdns")) sPrimaryDNS = request->getParam(PARAM_PDNS)->value();
      if (request->hasParam("sdns")) sSecondaryDNS = request->getParam(PARAM_SDNS)->value();
      if (request->hasParam("con")) con = true; else con = false;

      // http://192.168.1.118/cfg-save?apikey=1111&dhcp=on&ssid=TP-Link&password=
      // http://192.168.1.118/cfg-save?apikey=1111&localip=192.168.1.200&subnet=255.255.255.0&gateway=192.168.1.1&pdns=8.8.8.8&sdns=8.8.4.4&ssid=TP-Link&password=
      request->send(200, "text/plain", "Config saved - SSID:" + ssid + " APIKEY: " + apikey + " restart in 5 seconds");
      savePrefs();
      delay(2000);
      ESP.restart();
      //request->redirect("/");
    }
    else
      request->send(400, "text/plain", "Missing required parameters");
  });


  // Send a GET request to <IP>/get?message=<message>
  /*
  server.on("/sendmorse", HTTP_GET, [] (AsyncWebServerRequest * request) {
    if (request->hasParam(PARAM_APIKEY) && request->getParam(PARAM_APIKEY)->value() == apikey) {
      if (request->hasParam(PARAM_MESSAGE)) {
        // message = request->getParam(PARAM_MESSAGE)->value();
      }

      if (request->hasParam(PARAM_SPEED)) {
        sspeed = request->getParam(PARAM_SPEED)->value();
        speed = sspeed.toInt();
        RotaryEnc_KeyerSpeedWPM.cntVal = speed;
        //update_speed();
        Calc_WPM_dot_delay (speed);
        display_status_bar();
      }
      request->send(200, "text/plain", "OK");
    } else request->send(401, "text/plain", "Unauthorized");


  });
  */

  server.on("/js/bootstrap.bundle.min.js", HTTP_GET, [](AsyncWebServerRequest * request) {
    request->send(SPIFFS, "/js/bootstrap.bundle.min.js", "text/javascript");
  });

  server.on("/js/bootstrap4-toggle.min.js", HTTP_GET, [](AsyncWebServerRequest * request) {
    request->send(SPIFFS, "/js/bootstrap4-toggle.min.js", "text/css");
  });


  server.on("/js/jquery.mask.min.js", HTTP_GET, [](AsyncWebServerRequest * request) {
    request->send(SPIFFS, "/js/jquery.mask.min.js", "text/css");
  });

  server.on("/js/jquery-3.5.1.min.js", HTTP_GET, [](AsyncWebServerRequest * request) {
    request->send(SPIFFS, "/js/jquery-3.5.1.min.js", "text/css");
  });

  server.on("/css/bootstrap.min.css", HTTP_GET, [](AsyncWebServerRequest * request) {
    request->send(SPIFFS, "/css/bootstrap.min.css", "text/css");
  });


  server.on("/css/bootstrap4-toggle.min.css", HTTP_GET, [](AsyncWebServerRequest * request) {
    request->send(SPIFFS, "/css/bootstrap4-toggle.min.css", "text/css");
  });


  server.onNotFound(notFound);

  server.begin();

  if (udp.listen(UDP_PORT)) {
    Serial.print("UDP running at IP: ");
    Serial.print(IP);
    Serial.println(" port: 6789");
    udp.onPacket([](AsyncUDPPacket packet) {
      //Serial.print("Type of UDP datagram: ");
      //Serial.print(packet.isBroadcast() ? "Broadcast" : packet.isMulticast() ? "Multicast" : "Unicast");
      //Serial.print(", Sender: ");
      //Serial.print(packet.remoteIP());
      //Serial.print(":");
      //Serial.print(packet.remotePort());
      //Serial.print(", Receiver: ");
      //Serial.print(packet.localIP());
      //Serial.print(":");
      //Serial.print(packet.localPort());
      //Serial.print(", Message lenght: ");
      //Serial.print(packet.length());
      //Serial.print(", Payload: ");
      //Serial.write(packet.data(), packet.length());
      //Serial.println();
      udpdataString = (const char*)packet.data();
      udpdataString = udpdataString.substring(0, packet.length());
      char bb[5];
      int command = (int)packet.data()[1];
      if (packet.data()[0] == 27) {

        switch (command ) {
          //--------------------------
          case 0: //break cw
            xQueueReset( queue );
            break;
          //--------------------------
          case 50:  // set speed - CW Daemon command
            bb[0] = packet.data()[2];
            bb[1] = packet.data()[3];
            bb[2] = 0;
            speed = atoi(bb);
            sspeed = String(speed);
            //update_speed();
            RotaryEnc_KeyerSpeedWPM.cntVal = speed;
            Calc_WPM_dot_delay (speed);
            display_status_bar();
            //Serial.print("UDP Speed: ");
            //Serial.print(bb);
            break;
          //--------------------------
          case 0xCE:  // Config packEt = Set frequency + set WPM + set Power
            // WPM
            speed = ((uint32_t) packet.data()[6]);
            sspeed = String(speed);
            RotaryEnc_KeyerSpeedWPM.cntVal = speed;
            Calc_WPM_dot_delay(speed);
            // Power
            tmp32a = ((uint32_t) packet.data()[7]);
            RotaryEnc_OutPowerMiliWatt.cntVal = tmp32a;
            // Frequency word
            tmp32a = ((uint32_t) packet.data()[5])<<24;
            tmp32b = ((uint32_t) packet.data()[4])<<16;
            tmp32a += tmp32b;
            tmp32b = ((uint32_t) packet.data()[3])<<8;
            tmp32a += tmp32b;
            tmp32b = ((uint32_t) packet.data()[2]);
            tmp32a += tmp32b;
            RotaryEncISR.cntVal = tmp32a;
            RotaryEncISR.cntValOld = tmp32a + 1;
            params_set_by_udp_packet = true;
            program_state = S_RUN;
            break;
          //--------------------------
          default:
            break;
        }
      } else {
        //udpdataString.toUpperCase();
        //message += udpdataString;
        message = udpdataString;
        messageQueueSend();
        //Serial.print("UDP TX: ");
        //Serial.print(udpdataString);

      }

    });
  }


}


//
// JU: Modified function to set frequency since definition of FREQ_STEP was not precise enough (198.364 - should be 52e6/2**18=198.3642578125)
#define FREQ_STEP_JU 198.3642578125

void JUsetRfFrequency(uint32_t frequency, int32_t offset)
{

  // first we call original function so that private variables savedFrequency and savedOffset are updated
  //LT.setRfFrequency(frequency, offset);

  FreqWordNoOffset = FreqToRegWord(frequency);
  frequency = frequency + offset;
  uint8_t buffer[3];
  FreqWord = FreqToRegWord(frequency);
  buffer[0] = ( uint8_t )( ( FreqWord >> 16 ) & 0xFF );
  buffer[1] = ( uint8_t )( ( FreqWord >> 8 ) & 0xFF );
  buffer[2] = ( uint8_t )( FreqWord & 0xFF );
  LT.writeCommand(RADIO_SET_RFFREQUENCY, buffer, 3);
}

// Get RegWord from frequency
uint32_t FreqToRegWord(uint32_t frequency) {
  return ( uint32_t )( (double) frequency / (double)FREQ_STEP_JU);
}

// Get frequency from RegWord
uint32_t RegWordToFreq(uint32_t freqword) {
  return (uint32_t)((double)freqword * (double)FREQ_STEP_JU);
}

// Will add decimal point as separator between thousands, milions...
void format_freq(uint32_t n, char *out, bool params_set_by_udp_pkt)
{
  int c;
  char buf[20];
  char *p;
  if (params_set_by_udp_pkt == true) {
    sprintf(buf, "*%u", n);
  } else {
    sprintf(buf, " %u", n);
  }
  c = 2 - strlen(buf) % 3;
  for (p = buf; *p != 0; p++) {
    *out++ = *p;
    if (c == 1) {
      *out++ = '.';
    }
    c = (c + 1) % 3;
  }
  *--out = 0;
}

///////////////////////////////////////////////////////////
// This is the heart of the beacon.  Given a character, it finds the
// appropriate glyph and toggles output from the LoRa module to key the
// Feld Hell signal.
void encodechar(int ch) {
    int i, x, y, fch;
    word fbits;
     for (i=0; i<NGLYPHS; i++) {
        // Check each element of the glyphtab to see if we've found the
        // character we're trying to send.
        fch = pgm_read_byte(&glyphtab[i].ch);
        if (fch == ch) {
            // Found the character, now fetch the pattern to be transmitted,
            // one column at a time.
            for (x=0; x<7; x++) {
                fbits = pgm_read_word(&(glyphtab[i].col[x]));
                // Transmit (or do not tx) one 'pixel' at a time; characters
                // are 7 cols by 14 rows.
                for (y=0; y<14; y++) {
                    if (fbits & (1<<y)) {
                      startCW(); //TX tone
                    } else {
                      stopCW();  //TX tone off
                    }
                         
                    delayMicroseconds(4060);
                }
            }
            break; // We've found and transmitted the char,
                   // so exit the for loop
        }
    }
}

////////////////////////////////////////////////////////////////// 
// Loop through the string, transmitting one character at a time.
void encode_hell(char *str) {
    while (*str != '\0') 
        encodechar(*str++) ;
}
