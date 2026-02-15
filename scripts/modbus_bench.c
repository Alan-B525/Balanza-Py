/*
 * modbus_bench.c – Modbus RTU benchmark client (Windows)
 *
 * Self-contained: no external libraries needed.
 * Uses raw Win32 serial API for minimum overhead.
 *
 * Compile:  gcc -O2 -o modbus_bench.exe modbus_bench.c
 * Usage:    modbus_bench.exe COM9 3000000 1 1000 10
 *           (port, baud, slave_id, register, duration_s)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <windows.h>

/* ── CRC-16/Modbus ─────────────────────────────────────── */

static const unsigned short crc_table[256] = {
    0x0000,0xC0C1,0xC181,0x0140,0xC301,0x03C0,0x0280,0xC241,
    0xC601,0x06C0,0x0780,0xC741,0x0500,0xC5C1,0xC481,0x0440,
    0xCC01,0x0CC0,0x0D80,0xCD41,0x0F00,0xCFC1,0xCE81,0x0E40,
    0x0A00,0xCAC1,0xCB81,0x0B40,0xC901,0x09C0,0x0880,0xC841,
    0xD801,0x18C0,0x1980,0xD941,0x1B00,0xDBC1,0xDA81,0x1A40,
    0x1E00,0xDEC1,0xDF81,0x1F40,0xDD01,0x1DC0,0x1C80,0xDC41,
    0x1400,0xD4C1,0xD581,0x1540,0xD701,0x17C0,0x1680,0xD641,
    0xD201,0x12C0,0x1380,0xD341,0x1100,0xD1C1,0xD081,0x1040,
    0xF001,0x30C0,0x3180,0xF141,0x3300,0xF3C1,0xF281,0x3240,
    0x3600,0xF6C1,0xF781,0x3740,0xF501,0x35C0,0x3480,0xF441,
    0x3C00,0xFCC1,0xFD81,0x3D40,0xFF01,0x3FC0,0x3E80,0xFE41,
    0xFA01,0x3AC0,0x3B80,0xFB41,0x3900,0xF9C1,0xF881,0x3840,
    0x2800,0xE8C1,0xE981,0x2940,0xEB01,0x2BC0,0x2A80,0xEA41,
    0xEE01,0x2EC0,0x2F80,0xEF41,0x2D00,0xEDC1,0xEC81,0x2C40,
    0xE401,0x24C0,0x2580,0xE541,0x2700,0xE7C1,0xE681,0x2640,
    0x2200,0xE2C1,0xE381,0x2340,0xE101,0x21C0,0x2080,0xE041,
    0xA001,0x60C0,0x6180,0xA141,0x6300,0xA3C1,0xA281,0x6240,
    0x6600,0xA6C1,0xA781,0x6740,0xA501,0x65C0,0x6480,0xA441,
    0x6C00,0xACC1,0xAD81,0x6D40,0xAF01,0x6FC0,0x6E80,0xAE41,
    0xAA01,0x6AC0,0x6B80,0xAB41,0x6900,0xA9C1,0xA881,0x6840,
    0x7800,0xB8C1,0xB981,0x7940,0xBB01,0x7BC0,0x7A80,0xBA41,
    0xBE01,0x7EC0,0x7F80,0xBF41,0x7D00,0xBDC1,0xBC81,0x7C40,
    0xB401,0x74C0,0x7580,0xB541,0x7700,0xB7C1,0xB681,0x7640,
    0x7200,0xB2C1,0xB381,0x7340,0xB101,0x71C0,0x7080,0xB041,
    0x5000,0x90C1,0x9181,0x5140,0x9301,0x53C0,0x5280,0x9241,
    0x9601,0x56C0,0x5780,0x9741,0x5500,0x95C1,0x9481,0x5440,
    0x9C01,0x5CC0,0x5D80,0x9D41,0x5F00,0x9FC1,0x9E81,0x5E40,
    0x5A00,0x9AC1,0x9B81,0x5B40,0x9901,0x59C0,0x5880,0x9841,
    0x8801,0x48C0,0x4980,0x8941,0x4B00,0x8BC1,0x8A81,0x4A40,
    0x4E00,0x8EC1,0x8F81,0x4F40,0x8D01,0x4DC0,0x4C80,0x8C41,
    0x4400,0x84C1,0x8581,0x4540,0x8701,0x47C0,0x4680,0x8641,
    0x8201,0x42C0,0x4380,0x8341,0x4100,0x81C1,0x8081,0x4040,
};

static unsigned short crc16(const unsigned char *buf, int len) {
    unsigned short crc = 0xFFFF;
    for (int i = 0; i < len; i++) {
        crc = (crc >> 8) ^ crc_table[(crc ^ buf[i]) & 0xFF];
    }
    return crc;
}

/* ── Serial port ───────────────────────────────────────── */

static HANDLE open_serial(const char *port, DWORD baud) {
    char path[64];
    /* Handle COM ports > 9 */
    snprintf(path, sizeof(path), "\\\\.\\%s", port);

    HANDLE h = CreateFileA(path, GENERIC_READ | GENERIC_WRITE,
                           0, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        fprintf(stderr, "ERROR: Cannot open %s (error %lu)\n", port, GetLastError());
        return INVALID_HANDLE_VALUE;
    }

    DCB dcb;
    memset(&dcb, 0, sizeof(dcb));
    dcb.DCBlength = sizeof(dcb);
    GetCommState(h, &dcb);
    dcb.BaudRate  = baud;
    dcb.ByteSize  = 8;
    dcb.Parity    = NOPARITY;
    dcb.StopBits  = ONESTOPBIT;
    dcb.fBinary   = TRUE;
    dcb.fParity   = FALSE;
    dcb.fDtrControl = DTR_CONTROL_DISABLE;
    dcb.fRtsControl = RTS_CONTROL_DISABLE;
    SetCommState(h, &dcb);

    COMMTIMEOUTS to;
    memset(&to, 0, sizeof(to));
    /* Tight timeouts for maximum speed */
    to.ReadIntervalTimeout         = 1;   /* max ms between bytes */
    to.ReadTotalTimeoutMultiplier  = 0;
    to.ReadTotalTimeoutConstant    = 50;  /* max wait for first byte */
    to.WriteTotalTimeoutMultiplier = 0;
    to.WriteTotalTimeoutConstant   = 50;
    SetCommTimeouts(h, &to);

    /* Purge buffers */
    PurgeComm(h, PURGE_RXCLEAR | PURGE_TXCLEAR);

    return h;
}

/* ── Modbus RTU read holding registers ─────────────────── */

/*
 * Request:  [slave][0x03][addr_hi][addr_lo][qty_hi][qty_lo][crc_lo][crc_hi]
 * Response: [slave][0x03][byte_count][data...][crc_lo][crc_hi]
 *
 * For 2 registers: response = 1+1+1+4+2 = 9 bytes
 */

static int modbus_read_registers(HANDLE h, int slave, int addr, int qty,
                                  unsigned short *out_regs) {
    unsigned char req[8];
    req[0] = (unsigned char)slave;
    req[1] = 0x03;  /* Read Holding Registers */
    req[2] = (unsigned char)(addr >> 8);
    req[3] = (unsigned char)(addr & 0xFF);
    req[4] = (unsigned char)(qty >> 8);
    req[5] = (unsigned char)(qty & 0xFF);
    unsigned short c = crc16(req, 6);
    req[6] = (unsigned char)(c & 0xFF);
    req[7] = (unsigned char)(c >> 8);

    DWORD written;
    if (!WriteFile(h, req, 8, &written, NULL) || written != 8)
        return -1;

    /* Expected response size: 3 + 2*qty + 2 */
    int resp_len = 3 + 2 * qty + 2;
    unsigned char resp[256];
    DWORD total_read = 0;

    /* Read with minimal overhead: try to get all bytes at once */
    while ((int)total_read < resp_len) {
        DWORD got;
        if (!ReadFile(h, resp + total_read, resp_len - total_read, &got, NULL))
            return -2;
        if (got == 0)
            return -3;  /* timeout */
        total_read += got;
    }

    /* Verify CRC */
    unsigned short resp_crc = crc16(resp, resp_len - 2);
    unsigned short recv_crc = resp[resp_len - 2] | (resp[resp_len - 1] << 8);
    if (resp_crc != recv_crc)
        return -4;

    /* Verify slave and function */
    if (resp[0] != (unsigned char)slave || resp[1] != 0x03)
        return -5;

    /* Extract registers */
    for (int i = 0; i < qty; i++) {
        out_regs[i] = (resp[3 + 2*i] << 8) | resp[3 + 2*i + 1];
    }

    return 0;
}

/* ── High-resolution timer ─────────────────────────────── */

static LARGE_INTEGER qpc_freq;

static double now_ms(void) {
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart / (double)qpc_freq.QuadPart * 1000.0;
}

/* ── Sort for percentiles ──────────────────────────────── */

static int cmp_double(const void *a, const void *b) {
    double da = *(const double*)a;
    double db = *(const double*)b;
    return (da > db) - (da < db);
}

/* ── Main ──────────────────────────────────────────────── */

int main(int argc, char *argv[]) {
    if (argc < 3) {
        printf("Usage: modbus_bench.exe PORT BAUD [SLAVE_ID] [REGISTER] [DURATION_S]\n");
        printf("\nExamples:\n");
        printf("  modbus_bench.exe COM9 3000000\n");
        printf("  modbus_bench.exe COM9 3000000 1 1000 10\n");
        return 1;
    }

    const char *port   = argv[1];
    DWORD baud         = atoi(argv[2]);
    int slave_id       = argc > 3 ? atoi(argv[3]) : 1;
    int reg_addr       = argc > 4 ? atoi(argv[4]) : 1000;
    double duration_s  = argc > 5 ? atof(argv[5]) : 10.0;

    QueryPerformanceFrequency(&qpc_freq);

    printf("\n");
    printf("  ================================================\n");
    printf("  Modbus RTU Benchmark (C / Win32)\n");
    printf("  ================================================\n");
    printf("  Port:      %s\n", port);
    printf("  Baudrate:  %lu\n", (unsigned long)baud);
    printf("  Slave ID:  %d\n", slave_id);
    printf("  Register:  %d\n", reg_addr);
    printf("  Duration:  %.1f s\n", duration_s);
    printf("  ================================================\n\n");

    HANDLE h = open_serial(port, baud);
    if (h == INVALID_HANDLE_VALUE)
        return 1;

    printf("  Connected to %s\n", port);

    /* Test read */
    unsigned short test_regs[2];
    int rc = modbus_read_registers(h, slave_id, reg_addr, 2, test_regs);
    if (rc == 0) {
        int raw = (int)((test_regs[0] << 16) | test_regs[1]);
        printf("  First read OK: raw=%d (%.3f kg)\n\n", raw, raw / 1000.0);
    } else {
        printf("  WARNING: First read failed (rc=%d)\n\n", rc);
    }

    /* Allocate RTT buffer */
    int max_samples = (int)(duration_s * 5000) + 1000;  /* generous */
    double *rtts = (double*)malloc(max_samples * sizeof(double));
    if (!rtts) {
        fprintf(stderr, "ERROR: Out of memory\n");
        CloseHandle(h);
        return 1;
    }

    /* Warmup */
    printf("  Warmup (1s)...");
    fflush(stdout);
    double t_warm_end = now_ms() + 1000.0;
    while (now_ms() < t_warm_end) {
        modbus_read_registers(h, slave_id, reg_addr, 2, test_regs);
    }
    printf(" OK\n");

    /* Benchmark */
    printf("  Measuring (%.0fs)...", duration_s);
    fflush(stdout);

    int total = 0, errors = 0, value_changes = 0;
    int last_raw = -999999;
    double t_start = now_ms();
    double t_end = t_start + duration_s * 1000.0;

    while (now_ms() < t_end && total < max_samples) {
        unsigned short regs[2];
        double t0 = now_ms();
        rc = modbus_read_registers(h, slave_id, reg_addr, 2, regs);
        double t1 = now_ms();
        double rtt = t1 - t0;

        if (rc == 0) {
            int raw = (int)((regs[0] << 16) | regs[1]);
            if (raw != last_raw) {
                value_changes++;
                last_raw = raw;
            }
        } else {
            errors++;
        }

        rtts[total] = rtt;
        total++;
    }

    double elapsed_ms = now_ms() - t_start;
    double elapsed_s = elapsed_ms / 1000.0;
    printf(" OK\n\n");

    /* Statistics */
    int ok_count = total - errors;
    double throughput = total / elapsed_s;
    double update_hz = value_changes / elapsed_s;

    /* Sort for percentiles */
    qsort(rtts, total, sizeof(double), cmp_double);

    double min_rtt = rtts[0];
    double max_rtt = rtts[total - 1];
    double median  = rtts[total / 2];
    double p95     = rtts[(int)(total * 0.95)];
    double p99     = rtts[(int)(total * 0.99)];

    /* Mean and stdev */
    double sum = 0;
    for (int i = 0; i < total; i++) sum += rtts[i];
    double mean = sum / total;

    double var_sum = 0;
    for (int i = 0; i < total; i++) {
        double d = rtts[i] - mean;
        var_sum += d * d;
    }
    double stdev = 0;
    if (total > 1) {
        stdev = sqrt(var_sum / (total - 1));
    }

    printf("  +---------------------------------------------+\n");
    printf("  |  RESULTS                                    |\n");
    printf("  +---------------------------------------------+\n");
    printf("  |  Total reads:     %8d                  |\n", total);
    printf("  |  Successful:      %8d (%5.1f%%)          |\n", ok_count, 100.0*ok_count/total);
    printf("  |  Errors:          %8d                  |\n", errors);
    printf("  |  Value changes:   %8d                  |\n", value_changes);
    printf("  |  Elapsed:         %8.2f s                |\n", elapsed_s);
    printf("  |                                             |\n");
    printf("  |  THROUGHPUT:      %8.1f reads/s          |\n", throughput);
    printf("  |  Update rate:     %8.1f Hz               |\n", update_hz);
    printf("  |                                             |\n");
    printf("  |  RTT mean:        %8.3f ms               |\n", mean);
    printf("  |  RTT median:      %8.3f ms               |\n", median);
    printf("  |  RTT min:         %8.3f ms               |\n", min_rtt);
    printf("  |  RTT max:         %8.3f ms               |\n", max_rtt);
    printf("  |  RTT stdev:       %8.3f ms               |\n", stdev);
    printf("  |  RTT P95:         %8.3f ms               |\n", p95);
    printf("  |  RTT P99:         %8.3f ms               |\n", p99);
    printf("  +---------------------------------------------+\n");
    printf("\n  >> Max sustained speed: ~%.0f reads/s\n", throughput);

    if (errors == 0)
        printf("  >> No errors - stable connection\n");
    else
        printf("  >> WARNING: %d errors detected\n", errors);

    free(rtts);
    CloseHandle(h);
    printf("  >> Connection closed.\n\n");
    return 0;
}
