//
// Keeping original note from example coming with SX12XX library
//
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


// JU: LoRa1281F27 Module from NiceRF
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

//#define Program_Version "v1.0"
//#define Program_Version "v1.1"   // Corrected edge processing from rotary encoder 0x0E instead 0x01)
//#define Program_Version "v1.2"   // 2022-12-22 JU, Rotary encoder direction made configurable via menu
#define Program_Version "v1.3"     // 2023-02-02 JU, Added support for Iambic-B keying. Based on request of Markus DL6YYM


#define NSS 5                                  //select pin on LoRa device
#define SCK 18                                  //SCK on SPI3
#define MISO 19                                 //MISO on SPI3 
#define MOSI 23                                 //MOSI on SPI3 

#define NRESET 32                               //reset pin on LoRa device
#define RFBUSY 16                               //busy line

#define LED1 15                                 //on board LED, high for on
#define DIO1 13                                 //DIO1 pin on LoRa device, used for RX and TX done 
#define DIO2 -1                                 //DIO2 pin on LoRa device, normally not used so set to -1 
#define DIO3 -1                                 //DIO3 pin on LoRa device, normally not used so set to -1
#define RX_EN 4                                //pin for RX enable, used on some SX128X devices, set to -1 if not used
#define TX_EN 2                                 //pin for TX enable, used on some SX128X devices, set to -1 if not used
#define BUZZER 33                               //pin for buzzer, set to -1 if not used 
#define VCCPOWER 17    //JU-not needed by module          //pin controls power to external devices
#define LORA_DEVICE DEVICE_SX1281               //we need to define the device we are using
#define TCXO_EN 14
#define PTT_OUT 12

#define LOOP_PTT_MULT_VALUE 1000  // Value by which PttTimeout counter is multiplied - we need this since mail loop is running very fast
                                  // But be careful not to exceed max value of int32 variable of PttTimeout counter

// Pin definitions

#define ROTARY_ENC_A     26    // Rotary encoder contact A 
#define ROTARY_ENC_B     27    // Rotary encoder contact B 

#define ROTARY_ENC_PUSH  25    // Rotary encoder pushbutton
//
#define KEYER_DOT       34    // Morse keyer DOT          NOTE: GPIOs 34 to 39 INPUTs only / No internal pullup / No int. pulldown
#define KEYER_DASH      35    // Morse keyer DASH

//

#define NGLYPHS         (sizeof(glyphtab)/sizeof(glyphtab[0]))

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


const uint16_t  Morse_Coding_table2 [] = {
7*256 + 0b00000000,	// ......  	0 no valid morse code, len = 7
6*256 + 0b00000000,	// ......  	1 no valid morse code, len = 6
5*265 + '5',		    // .....    	2 '5'
6*256 + 0b00000001,	// .....-  	3 no valid morse code, len = 6
4*265 + 'H',		    // ....     	4 'H'
6*256 + 0b00000010,	// ....-.  	5 no valid morse code, len = 6
5*265 + '4',		    // ....-    	6 '4'
6*256 + 0b00000011,	// ....--  	7 no valid morse code, len = 6
3*265 + 'S',		    // ...      	8 'S'
6*256 + 0b00000100,	// ...-..  	9 no valid morse code, len = 6
5*256 + 0b00000010,	// ...-.   	10 no valid morse code, len = 5
6*256 + 0b00000101,	// ...-.-  	11 no valid morse code, len = 6
4*265 + 'V',		    // ...-     	12 'V'
6*256 + 0b00000110,	// ...--.  	13 no valid morse code, len = 6
5*265 + '3',		    // ...--    	14 '3'
6*256 + 0b00000111,	// ...---  	15 no valid morse code, len = 6
2*265 + 'I',		    // ..       	16 'I'
6*256 + 0b00001000,	// ..-...  	17 no valid morse code, len = 6
5*256 + 0b00000100,	// ..-..   	18 no valid morse code, len = 5
6*256 + 0b00001001,	// ..-..-  	19 no valid morse code, len = 6
4*265 + 'F',		    // ..-.     	20 'F'
6*256 + 0b00001010,	// ..-.-.  	21 no valid morse code, len = 6
5*256 + 0b00000101,	// ..-.-   	22 no valid morse code, len = 5
6*256 + 0b00001011,	// ..-.--  	23 no valid morse code, len = 6
3*265 + 'U',		    // ..-      	24 'U'
6*265 + '?',		    // ..--..   	25 '?'
5*256 + 0b00000110,	// ..--.   	26 no valid morse code, len = 5
6*265 + '_',		    // ..--.-   	27 '_'
4*256 + 0b00000011,	// ..--    	28 no valid morse code, len = 4
6*256 + 0b00001110,	// ..---.  	29 no valid morse code, len = 6
5*265 + '2',		    // ..---    	30 '2'
6*256 + 0b00001111,	// ..----  	31 no valid morse code, len = 6
1*265 + 'E',		    // .        	32 'E'
6*256 + 0b00010000,	// .-....  	33 no valid morse code, len = 6
5*265 + '&',		    // .-...    	34 '&'
6*256 + 0b00010001,	// .-...-  	35 no valid morse code, len = 6
4*265 + 'L',		    // .-..     	36 'L'
6*265 + '"',		    // .-..-.   	37 '"'
5*256 + 0b00001001,	// .-..-   	38 no valid morse code, len = 5
6*256 + 0b00010011,	// .-..--  	39 no valid morse code, len = 6
3*265 + 'R',		    // .-.      	40 'R'
6*256 + 0b00010100,	// .-.-..  	41 no valid morse code, len = 6
5*265 + '+',		    // .-.-.    	42 '+'
6*265 + '.',		    // .-.-.-   	43 '.'
4*256 + 0b00000101,	// .-.-    	44 no valid morse code, len = 4
6*256 + 0b00010110,	// .-.--.  	45 no valid morse code, len = 6
5*256 + 0b00001011,	// .-.--   	46 no valid morse code, len = 5
6*256 + 0b00010111,	// .-.---  	47 no valid morse code, len = 6
2*265 + 'A',		    // .-       	48 'A'
6*256 + 0b00011000,	// .--...  	49 no valid morse code, len = 6
5*256 + 0b00001100,	// .--..   	50 no valid morse code, len = 5
6*256 + 0b00011001,	// .--..-  	51 no valid morse code, len = 6
4*265 + 'P',		    // .--.     	52 'P'
6*265 + '@',		    // .--.-.   	53 '@'
5*256 + 0b00001101,	// .--.-   	54 no valid morse code, len = 5
6*256 + 0b00011011,	// .--.--  	55 no valid morse code, len = 6
3*265 + 'W',		    // .--      	56 'W'
6*256 + 0b00011100,	// .---..  	57 no valid morse code, len = 6
5*256 + 0b00001110,	// .---.   	58 no valid morse code, len = 5
6*256 + 0b00011101,	// .---.-  	59 no valid morse code, len = 6
4*265 + 'J',		    // .---     	60 'J'
6*265 + '\'',		    // .----.   	61 '''
5*265 + '1',		    // .----    	62 '1'
6*256 + 0b00011111,	// .-----  	63 no valid morse code, len = 6
0*256 + 0b00000000,	//         	64 no valid morse code, len = 0
6*256 + 0b00100000,	// -.....  	65 no valid morse code, len = 6
5*265 + '6',		    // -....    	66 '6'
6*265 + '-',		    // -....-   	67 '-'
4*265 + 'B',		    // -...     	68 'B'
6*256 + 0b00100010,	// -...-.  	69 no valid morse code, len = 6
5*265 + '=',		    // -...-    	70 '='
6*256 + 0b00100011,	// -...--  	71 no valid morse code, len = 6
3*265 + 'D',		    // -..      	72 'D'
6*256 + 0b00100100,	// -..-..  	73 no valid morse code, len = 6
5*265 + '/',		    // -..-.    	74 '/'
6*256 + 0b00100101,	// -..-.-  	75 no valid morse code, len = 6
4*265 + 'X',		    // -..-     	76 'X'
6*256 + 0b00100110,	// -..--.  	77 no valid morse code, len = 6
5*256 + 0b00010011,	// -..--   	78 no valid morse code, len = 5
6*256 + 0b00100111,	// -..---  	79 no valid morse code, len = 6
2*265 + 'N',		    // -.       	80 'N'
6*256 + 0b00101000,	// -.-...  	81 no valid morse code, len = 6
5*256 + 0b00010100,	// -.-..   	82 no valid morse code, len = 5
6*256 + 0b00101001,	// -.-..-  	83 no valid morse code, len = 6
4*265 + 'C',		    // -.-.     	84 'C'
6*265 + ';',		    // -.-.-.   	85 ';'
5*256 + 0b00010101,	// -.-.-   	86 no valid morse code, len = 5
6*265 + '!',		    // -.-.--   	87 '!'
3*265 + 'K',		    // -.-      	88 'K'
6*256 + 0b00101100,	// -.--..  	89 no valid morse code, len = 6
5*265 + '(',		    // -.--.    	90 '('
6*265 + ')',		    // -.--.-   	91 ')'
4*265 + 'Y',		    // -.--     	92 'Y'
6*256 + 0b00101110,	// -.---.  	93 no valid morse code, len = 6
5*256 + 0b00010111,	// -.---   	94 no valid morse code, len = 5
6*256 + 0b00101111,	// -.----  	95 no valid morse code, len = 6
1*265 + 'T',		    // -        	96 'T'
6*256 + 0b00110000,	// --....  	97 no valid morse code, len = 6
5*265 + '7',		    // --...    	98 '7'
6*256 + 0b00110001,	// --...-  	99 no valid morse code, len = 6
4*265 + 'Z',		    // --..     	100 'Z'
6*256 + 0b00110010,	// --..-.  	101 no valid morse code, len = 6
5*256 + 0b00011001,	// --..-   	102 no valid morse code, len = 5
6*265 + ',',		    // --..--   	103 ','
3*265 + 'G',		    // --.      	104 'G'
6*256 + 0b00110100,	// --.-..  	105 no valid morse code, len = 6
5*256 + 0b00011010,	// --.-.   	106 no valid morse code, len = 5
6*256 + 0b00110101,	// --.-.-  	107 no valid morse code, len = 6
4*265 + 'Q',		    // --.-     	108 'Q'
6*256 + 0b00110110,	// --.--.  	109 no valid morse code, len = 6
5*256 + 0b00011011,	// --.--   	110 no valid morse code, len = 5
6*256 + 0b00110111,	// --.---  	111 no valid morse code, len = 6
2*265 + 'M',		    // --       	112 'M'
6*265 + ':',		    // ---...   	113 ':'
5*265 + '8',		    // ---..    	114 '8'
6*256 + 0b00111001,	// ---..-  	115 no valid morse code, len = 6
4*256 + 0b00001110,	// ---.    	116 no valid morse code, len = 4
6*256 + 0b00111010,	// ---.-.  	117 no valid morse code, len = 6
5*256 + 0b00011101,	// ---.-   	118 no valid morse code, len = 5
6*256 + 0b00111011,	// ---.--  	119 no valid morse code, len = 6
3*265 + 'O',		    // ---      	120 'O'
6*256 + 0b00111100,	// ----..  	121 no valid morse code, len = 6
5*265 + '9',		    // ----.    	122 '9'
6*256 + 0b00111101,	// ----.-  	123 no valid morse code, len = 6
4*256 + 0b00001111,	// ----    	124 no valid morse code, len = 4
6*256 + 0b00111110,	// -----.  	125 no valid morse code, len = 6
5*265 + '0',		    // -----    	126 '0'
6*256 + 0b00111111	// ------  	127 no valid morse code, len = 6
};




// Build the Feld Hell "font".  This is declared PROGMEM to save
// memory on the Arduino; this data will be stored in program
// flash instead of loaded in memory.  This makes accesses slower
// and more complicated, but this is a small price to pay for the
// memory savings

// Define the structure of a glyph
typedef struct glyph {
    char ch ;
    word col[7] ;
} Glyph ;
 

const Glyph glyphtab[] PROGMEM = {
  {' ', {0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000}},
  {'A', {0x07fc, 0x0e60, 0x0c60, 0x0e60, 0x07fc, 0x0000, 0x0000}},
  {'B', {0x0c0c, 0x0ffc, 0x0ccc, 0x0ccc, 0x0738, 0x0000, 0x0000}},
  {'C', {0x0ffc, 0x0c0c, 0x0c0c, 0x0c0c, 0x0c0c, 0x0000, 0x0000}},
  {'D', {0x0c0c, 0x0ffc, 0x0c0c, 0x0c0c, 0x07f8, 0x0000, 0x0000}},
  {'E', {0x0ffc, 0x0ccc, 0x0ccc, 0x0c0c, 0x0c0c, 0x0000, 0x0000}},
  {'F', {0x0ffc, 0x0cc0, 0x0cc0, 0x0c00, 0x0c00, 0x0000, 0x0000}},
  {'G', {0x0ffc, 0x0c0c, 0x0c0c, 0x0ccc, 0x0cfc, 0x0000, 0x0000}},
  {'H', {0x0ffc, 0x00c0, 0x00c0, 0x00c0, 0x0ffc, 0x0000, 0x0000}},
  {'I', {0x0ffc, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000}},
  {'J', {0x003c, 0x000c, 0x000c, 0x000c, 0x0ffc, 0x0000, 0x0000}},
  {'K', {0x0ffc, 0x00c0, 0x00e0, 0x0330, 0x0e1c, 0x0000, 0x0000}},
  {'L', {0x0ffc, 0x000c, 0x000c, 0x000c, 0x000c, 0x0000, 0x0000}},
  {'M', {0x0ffc, 0x0600, 0x0300, 0x0600, 0x0ffc, 0x0000, 0x0000}},
  {'N', {0x0ffc, 0x0700, 0x01c0, 0x0070, 0x0ffc, 0x0000, 0x0000}},
  {'O', {0x0ffc, 0x0c0c, 0x0c0c, 0x0c0c, 0x0ffc, 0x0000, 0x0000}},
  {'P', {0x0c0c, 0x0ffc, 0x0ccc, 0x0cc0, 0x0780, 0x0000, 0x0000}},
  {'Q', {0x0ffc, 0x0c0c, 0x0c3c, 0x0ffc, 0x000f, 0x0000, 0x0000}},
  {'R', {0x0ffc, 0x0cc0, 0x0cc0, 0x0cf0, 0x079c, 0x0000, 0x0000}},
  {'S', {0x078c, 0x0ccc, 0x0ccc, 0x0ccc, 0x0c78, 0x0000, 0x0000}},
  {'T', {0x0c00, 0x0c00, 0x0ffc, 0x0c00, 0x0c00, 0x0000, 0x0000}},
  {'U', {0x0ff8, 0x000c, 0x000c, 0x000c, 0x0ff8, 0x0000, 0x0000}},
  {'V', {0x0ffc, 0x0038, 0x00e0, 0x0380, 0x0e00, 0x0000, 0x0000}},
  {'W', {0x0ff8, 0x000c, 0x00f8, 0x000c, 0x0ff8, 0x0000, 0x0000}},
  {'X', {0x0e1c, 0x0330, 0x01e0, 0x0330, 0x0e1c, 0x0000, 0x0000}},
  {'Y', {0x0e00, 0x0380, 0x00fc, 0x0380, 0x0e00, 0x0000, 0x0000}},
  {'Z', {0x0c1c, 0x0c7c, 0x0ccc, 0x0f8c, 0x0e0c, 0x0000, 0x0000}},
  {'0', {0x07f8, 0x0c0c, 0x0c0c, 0x0c0c, 0x07f8, 0x0000, 0x0000}},
  {'1', {0x0300, 0x0600, 0x0ffc, 0x0000, 0x0000, 0x0000, 0x0000}},
  {'2', {0x061c, 0x0c3c, 0x0ccc, 0x078c, 0x000c, 0x0000, 0x0000}},
  {'3', {0x0006, 0x1806, 0x198c, 0x1f98, 0x00f0, 0x0000, 0x0000}},
  {'4', {0x1fe0, 0x0060, 0x0060, 0x0ffc, 0x0060, 0x0000, 0x0000}},
  {'5', {0x000c, 0x000c, 0x1f8c, 0x1998, 0x18f0, 0x0000, 0x0000}},
  {'6', {0x07fc, 0x0c66, 0x18c6, 0x00c6, 0x007c, 0x0000, 0x0000}},
  {'7', {0x181c, 0x1870, 0x19c0, 0x1f00, 0x1c00, 0x0000, 0x0000}},
  {'8', {0x0f3c, 0x19e6, 0x18c6, 0x19e6, 0x0f3c, 0x0000, 0x0000}},
  {'9', {0x0f80, 0x18c6, 0x18cc, 0x1818, 0x0ff0, 0x0000, 0x0000}},
  {'*', {0x018c, 0x0198, 0x0ff0, 0x0198, 0x018c, 0x0000, 0x0000}},
  {'.', {0x001c, 0x001c, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000}},
  {'?', {0x1800, 0x1800, 0x19ce, 0x1f00, 0x0000, 0x0000, 0x0000}},
  {'!', {0x1f9c, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000}},
  {'(', {0x01e0, 0x0738, 0x1c0e, 0x0000, 0x0000, 0x0000, 0x0000}},
  {')', {0x1c0e, 0x0738, 0x01e0, 0x0000, 0x0000, 0x0000, 0x0000}},
  {'#', {0x0330, 0x0ffc, 0x0330, 0x0ffc, 0x0330, 0x0000, 0x0000}},
  {'$', {0x078c, 0x0ccc, 0x1ffe, 0x0ccc, 0x0c78, 0x0000, 0x0000}},
  {'/', {0x001c, 0x0070, 0x01c0, 0x0700, 0x1c00, 0x0000, 0x0000}},
} ;
