/*******************************************************************************************************
  Programs for Arduino - Copyright of the author Stuart Robinson - 02/03/20

  This program is supplied as is, it is up to the user of the program to decide if the program is
  suitable for the intended purpose and free from errors.
*******************************************************************************************************/

//*******  Setup hardware pin definitions here ! ***************

//These are the pin definitions for one of my own boards, a ESP32 shield base with BBF board shield on
//top. Be sure to change the definitions to match your own setup. Some pins such as DIO2, DIO3, BUZZER
//may not be in used by this sketch so they do not need to be connected and should be included and be 
//set to -1.


// LoRa1281F27 Module from NiceRF
//
// 1 VCC 		- 2.0-5.5v Connected to the positive pole of the power supply
// 2 GND 		- Power ground
// 3 NRESET 	I 0-3.3V Chip reset trigger pin, active low
// 4 BUSY 		O 0-3.3V Status indicator pin (see SX1280/1281 specification for details)
// 5 DIO1 		O 0-3.3V
// 6 DIO2 		O 0-3.3V
// 7 DIO3 		O 0-3.3V
// 8 NSS 		I 0-3.3V Module chip select pin
// 9 SCK 		I 0-3.3V SPI clock input pin
// 10 MOSI 	I 0-3.3V SPI data input pin
// 11 MISO 	O 0-3.3V SPI data output pin
// 12,15.16 	GND - - Connected to the negative pole
// 13 TXEN 	I 0-3.3V
// 14 RXEN 	I 0-3.3V
// 17 			ANT - - Connect with 50 ohm coaxial antenna
// 18 			GND - - Connected to the negative pole

// https://github.com/Xinyuan-LilyGO/TTGO-T-Display/issues/14 :
//Found the answer, the following pin mappings worked for me:
//#define PIN_MISO  27  // GPIO27
//#define PIN_MOSI  26  // GPIO26
//#define PIN_SCK   25  // GIPO25
//#define PIN_CS    33  // GPIO33

// https://www.esp32.com/viewtopic.php?t=13697 :
// you can only use GPIO34 and higher as inputs, not outputs 

#define Program_Version "QO-100 TX SX1281 V0.2"


#define NSS 5                                  //select pin on LoRa device
#define SCK 18                                  //SCK on SPI3
#define MISO 19                                 //MISO on SPI3 
#define MOSI 23                                 //MOSI on SPI3 

#define NRESET 32                               //reset pin on LoRa device
#define RFBUSY 16                               //busy line

#define LED1 12                                 //on board LED, high for on
#define DIO1 13                                 //DIO1 pin on LoRa device, used for RX and TX done 
#define DIO2 -1                                 //DIO2 pin on LoRa device, normally not used so set to -1 
#define DIO3 -1                                 //DIO3 pin on LoRa device, normally not used so set to -1
#define RX_EN 4                                //pin for RX enable, used on some SX128X devices, set to -1 if not used
#define TX_EN 2                                 //pin for TX enable, used on some SX128X devices, set to -1 if not used
#define BUZZER 33                               //pin for buzzer, set to -1 if not used 
#define VCCPOWER 17    //JU-not needed by module          //pin controls power to external devices
#define LORA_DEVICE DEVICE_SX1281               //we need to define the device we are using
#define TCXO_EN 14

// Pin definitions
#define ROTARY_ENC_A     26    // Rotary encoder contact A 
#define ROTARY_ENC_B     27    // Rotary encoder contact B 
#define ROTARY_ENC_PUSH  25    // Rotary encoder pushbutton
//
#define KEYER_DOT       34    // Morse keyer DOT          NOTE: GPIOs 34 to 39 INPUTs only / No internal pullup / No int. pulldown
#define KEYER_DASH      35    // Morse keyer DASH
//


//*******  Setup LoRa Parameters Here ! ***************

//LoRa Modem Parameters
//const uint32_t Frequency = 2445000000;          //frequency of transmissions
const uint32_t Frequency = 2400020000;            //frequency of transmissions
const int32_t Offset = 0;                         //offset frequency for calibration purposes  
//const uint8_t Bandwidth = LORA_BW_0400;         //LoRa bandwidth
const uint8_t Bandwidth = LORA_BW_0200;           //LoRa bandwidth
//const uint8_t SpreadingFactor = LORA_SF7;       //LoRa spreading factor
const uint8_t SpreadingFactor = LORA_SF11;        //LoRa spreading factor
const uint8_t CodeRate = LORA_CR_4_5;             //LoRa coding rate

//const int8_t TXpower = 10;                      //LoRa transmit power in dBm
const int8_t TXpower = 13;                        //LoRa transmit power in dBm

const uint16_t packet_delay = 1000;               //mS delay between packets

// OM2JU
const uint8_t  Morse_Coding_table [] = {
0x00,   // Space = do not play anything just intercharacter delay
0xEB,   // !	-.-.-- => len = 110 char=101011 => 11101011 = EB
0xD2,   // "
0x00,   // # ?
0x00,   // $ ?
0x00,   // % ?
0x00,   // & ?
0xDE,   // '
0xB6,   // (
0xED,   // )
0x00,   // * ?
0xAA,   // +	.-.-. => len=101 char=01010     => 10101010 = AA
0xF3,   // ,	--..-- => len = 110 char=110011 => 11110011 = F3
0xE1,   // -
0xD5,   // .
0xB2,   // /
0xBF,   // 0
0xAF,   // 1
0xA7,   // 2
0xA3,   // 3
0xA1,   // 4
0xA0,   // 5
0xB0,   // 6
0xB8,   // 7
0xBC,   // 8
0xBE,   // 9
0xF8,   // :
0xEA,   // ;
0x00,   // < ?
0xB1,   // =
0x00,   // > ?
0xCC,   // ?
0xDA,   // @
0x48,   // A
0x90,   // B
0x94,   // C
0x70,   // D
0x20,   // E
0x84,   // F
0x78,   // G
0x80,   // H
0x40,   // I
0x8E,   // J
0x74,   // K
0x88,   // L
0x58,   // M
0x50,   // N
0x7C,   // O
0x8C,   // P
0x9A,   // Q
0x68,   // R
0x60,   // S
0x30,   // T
0x64,   // U
0x82,   // V
0x6C,   // W
0x92,   // X
0x96,   // Y
0x98,   // Z
0x00,   // [ ?
0x00,   // \ ?
0x00,   // ] ?
0x00,   // ^ ?
0xCD,   // _
0x00    // ` ?
};
