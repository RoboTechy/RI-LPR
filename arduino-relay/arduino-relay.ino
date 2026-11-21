/*
  RI-LPR traffic light relay - Arduino Mega 2560 + Ethernet shield (W5100)

  The same job as ../pi-relay-service (the Raspberry Pi version), with the
  same HTTP commands, so the backend works with either one: only
  PI_RELAY_SERVICE_URL in backend/.env points at one or the other.

  Each line has one output pin:   1 (HIGH, 5 V) = green     0 (LOW) = red
  Red is the idle state: the pins are driven LOW the moment the board starts.

  API (every command but /health needs the header  X-API-Key: <API_KEY>):
    POST /light/{n}/green[?seconds=N]  green; back to red after N seconds
                                       (N = 0: stays green until /red;
                                       no ?seconds=: DEFAULT_GREEN_SECONDS)
    POST /light/{n}/red                red at once
    POST /light/{n}/red-if-auto        does nothing (kept for the backend)
    GET  /light/{n}                    {"line_number":n,"color":"red"|"green"}
    GET  /lights                       {"1":"red","2":"green",...}
    GET  /health                       no key; {"status":"ok","lines":[...]}

  Libraries: SPI and Ethernet (both ship with the Arduino IDE).
  Board: "Arduino Mega or Mega 2560".  Setup and wiring: see README.md.
*/
#include <SPI.h>
#include <Ethernet.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

// ============================== SETTINGS ===============================

// Network: pick a free address on the same network as the backend can reach
// (fixed, not DHCP). MAC: any value that is unique on your network.
byte MAC[] = {0xDE, 0xAD, 0xBE, 0xEF, 0x20, 0x01};
IPAddress LOCAL_IP(192, 168, 203, 123);
IPAddress GATEWAY(192, 168, 203, 1);
IPAddress SUBNET(255, 255, 255, 0);
IPAddress DNS_SERVER(192, 168, 203, 1);
const uint16_t HTTP_PORT = 8080;

// Must equal PI_RELAY_API_KEY in the backend's .env. At most 60 characters.
const char API_KEY[] = "change-me-relay-key";

// Pin of each line (index 0 = line 1). 22-27 avoid everything the Ethernet
// shield uses on a Mega (4, 10, 50-53) and the USB serial pins (0, 1).
const uint8_t NUM_LINES = 6;
const uint8_t LINE_PINS[NUM_LINES] = {22, 23, 24, 25, 26, 27};

// true: pin HIGH = green, LOW = red. Set false if your relay board is
// active-low and you want the relay OFF for red.
const bool GREEN_IS_HIGH = true;

// Used when a green command carries no ?seconds=.
const unsigned long DEFAULT_GREEN_SECONDS = 30;

// 1: reset the board by itself if the program ever hangs (needs a Mega
// bootloader that supports the watchdog - leave 0 if unsure).
#define USE_WATCHDOG 0

// ======================================================================

#if USE_WATCHDOG
#include <avr/wdt.h>
#endif

const uint8_t RED_LEVEL = GREEN_IS_HIGH ? LOW : HIGH;
const uint8_t GREEN_LEVEL = GREEN_IS_HIGH ? HIGH : LOW;
const unsigned long MAX_SECONDS = 86400UL;
const unsigned long CLIENT_TIMEOUT_MS = 1000;

struct Light {
  bool green;
  bool timed;           // false: stays green until set red
  unsigned long until;  // millis() value at which a timed green ends
};

Light lights[NUM_LINES];
EthernetServer server(HTTP_PORT);

void setRed(uint8_t i) {
  digitalWrite(LINE_PINS[i], RED_LEVEL);
  lights[i].green = false;
  lights[i].timed = false;
}

void setGreen(uint8_t i, unsigned long ms) {  // ms == 0: no timer
  digitalWrite(LINE_PINS[i], GREEN_LEVEL);
  lights[i].green = true;
  lights[i].timed = ms > 0;
  lights[i].until = millis() + ms;
}

// Turns a timed green off when its time is up. The signed difference keeps
// this correct when millis() wraps around (every ~49 days).
void checkTimers() {
  for (uint8_t i = 0; i < NUM_LINES; i++) {
    if (lights[i].green && lights[i].timed &&
        (long)(millis() - lights[i].until) >= 0) {
      setRed(i);
    }
  }
}

// Reads one line (without the line ending) into buf; longer lines are cut.
// Returns false if the client stopped or timed out first.
bool readLine(EthernetClient &c, char *buf, uint8_t size) {
  uint8_t len = 0;
  unsigned long start = millis();
  while (millis() - start < CLIENT_TIMEOUT_MS) {
    checkTimers();
    if (c.available()) {
      int ch = c.read();
      if (ch == '\n') {
        buf[len] = 0;
        return true;
      }
      if (ch != '\r' && len < size - 1) buf[len++] = (char)ch;
    } else if (!c.connected()) {
      break;
    }
  }
  buf[len] = 0;
  return false;
}

void respond(EthernetClient &c, int code, const char *body) {
  const char *text = code == 200 ? "OK"
                   : code == 400 ? "Bad Request"
                   : code == 401 ? "Unauthorized"
                   : code == 404 ? "Not Found"
                                 : "Method Not Allowed";
  c.print(F("HTTP/1.1 "));
  c.print(code);
  c.print(' ');
  c.println(text);
  c.println(F("Content-Type: application/json"));
  c.print(F("Content-Length: "));
  c.println((int)strlen(body));
  c.println(F("Connection: close"));
  c.println();
  c.print(body);
}

// Finds "seconds=<number>" in the query. Returns 0 = absent, 1 = valid
// (value in *out), -1 = present but invalid.
int parseSeconds(const char *query, double *out) {
  const char *p = strstr(query, "seconds=");
  if (p == NULL) return 0;
  p += 8;
  char *end;
  double v = strtod(p, &end);
  if (end == p || v < 0 || v > (double)MAX_SECONDS) return -1;
  *out = v;
  return 1;
}

void handleRequest(EthernetClient &c) {
  char line[100];
  if (!readLine(c, line, sizeof(line))) return;

  // "METHOD /path?query HTTP/1.1"
  char *method = line;
  char *sp = strchr(line, ' ');
  if (sp == NULL) return;
  *sp = 0;
  char *path = sp + 1;
  sp = strchr(path, ' ');
  if (sp != NULL) *sp = 0;

  // headers: only X-API-Key matters
  bool authOk = false;
  char hdr[100];
  for (uint8_t n = 0; n < 24; n++) {
    if (!readLine(c, hdr, sizeof(hdr))) break;
    if (hdr[0] == 0) break;  // blank line: end of headers
    if (strncasecmp(hdr, "x-api-key:", 10) == 0) {
      char *v = hdr + 10;
      while (*v == ' ') v++;
      size_t l = strlen(v);
      while (l > 0 && (v[l - 1] == ' ' || v[l - 1] == '\t')) v[--l] = 0;
      authOk = strcmp(v, API_KEY) == 0;
    }
  }

  char *query = strchr(path, '?');
  if (query != NULL) *query++ = 0; else query = path + strlen(path);

  Serial.print(method);
  Serial.print(' ');
  Serial.println(path);

  bool isGet = strcmp(method, "GET") == 0;
  bool isPost = strcmp(method, "POST") == 0;
  char body[160];

  if (strcmp(path, "/health") == 0) {
    if (!isGet) { respond(c, 405, "{\"detail\":\"method not allowed\"}"); return; }
    respond(c, 200, "{\"status\":\"ok\",\"lines\":[1,2,3,4,5,6]}");
    return;
  }

  if (!authOk) {
    respond(c, 401, "{\"detail\":\"invalid API key\"}");
    return;
  }

  if (strcmp(path, "/lights") == 0) {
    if (!isGet) { respond(c, 405, "{\"detail\":\"method not allowed\"}"); return; }
    int pos = snprintf(body, sizeof(body), "{");
    for (uint8_t i = 0; i < NUM_LINES; i++) {
      pos += snprintf(body + pos, sizeof(body) - pos, "%s\"%d\":\"%s\"",
                      i ? "," : "", i + 1, lights[i].green ? "green" : "red");
    }
    snprintf(body + pos, sizeof(body) - pos, "}");
    respond(c, 200, body);
    return;
  }

  if (strncmp(path, "/light/", 7) == 0) {
    char *rest;
    long n = strtol(path + 7, &rest, 10);
    if (rest == path + 7 || n < 1 || n > NUM_LINES) {
      snprintf(body, sizeof(body), "{\"detail\":\"no relay configured for line %ld\"}", n);
      respond(c, 404, body);
      return;
    }
    uint8_t i = (uint8_t)(n - 1);

    if (*rest == 0) {  // GET /light/{n}
      if (!isGet) { respond(c, 405, "{\"detail\":\"method not allowed\"}"); return; }
      snprintf(body, sizeof(body), "{\"line_number\":%ld,\"color\":\"%s\"}", n,
               lights[i].green ? "green" : "red");
      respond(c, 200, body);
      return;
    }

    if (!isPost) { respond(c, 405, "{\"detail\":\"method not allowed\"}"); return; }

    if (strcmp(rest, "/green") == 0) {
      double seconds = (double)DEFAULT_GREEN_SECONDS;
      int parsed = parseSeconds(query, &seconds);
      if (parsed < 0) {
        respond(c, 400, "{\"detail\":\"seconds must be between 0 and 86400\"}");
        return;
      }
      unsigned long ms = (unsigned long)(seconds * 1000.0);
      if (seconds > 0 && ms == 0) ms = 1;
      setGreen(i, ms);
      snprintf(body, sizeof(body), "{\"line_number\":%ld,\"color\":\"green\",\"seconds\":%lu}", n,
               (unsigned long)seconds);
      respond(c, 200, body);
      return;
    }
    if (strcmp(rest, "/red") == 0) {
      setRed(i);
      snprintf(body, sizeof(body), "{\"line_number\":%ld,\"color\":\"red\"}", n);
      respond(c, 200, body);
      return;
    }
    if (strcmp(rest, "/red-if-auto") == 0) {  // a no-op, like the Pi version
      snprintf(body, sizeof(body), "{\"line_number\":%ld,\"color\":\"%s\"}", n,
               lights[i].green ? "green" : "red");
      respond(c, 200, body);
      return;
    }
  }

  respond(c, 404, "{\"detail\":\"not found\"}");
}

void setup() {
  // Lights first: every pin goes to RED before anything else happens. The
  // level is written before the pin becomes an output, so it never glitches.
  for (uint8_t i = 0; i < NUM_LINES; i++) {
    digitalWrite(LINE_PINS[i], RED_LEVEL);
    pinMode(LINE_PINS[i], OUTPUT);
    lights[i].green = false;
    lights[i].timed = false;
    lights[i].until = 0;
  }

  Serial.begin(115200);

  // Ethernet shield housekeeping on a Mega: SPI master pin, W5100 select,
  // and the shield's SD card kept deselected.
  pinMode(53, OUTPUT);
  pinMode(10, OUTPUT);
  digitalWrite(10, HIGH);
  pinMode(4, OUTPUT);
  digitalWrite(4, HIGH);

  Ethernet.begin(MAC, LOCAL_IP, DNS_SERVER, GATEWAY, SUBNET);
  server.begin();

  Serial.print(F("RI-LPR relay ready at "));
  Serial.print(Ethernet.localIP());
  Serial.print(':');
  Serial.println(HTTP_PORT);

#if USE_WATCHDOG
  wdt_enable(WDTO_8S);
#endif
}

void loop() {
  checkTimers();
  EthernetClient client = server.available();
  if (client) {
    handleRequest(client);
    delay(1);
    client.stop();
  }
#if USE_WATCHDOG
  wdt_reset();
#endif
}
